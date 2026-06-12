"""
TensorRT FP16 Export Script for Face/Body ReID Pipeline.
Converts SCRFD, GlintR100 (ArcFace), and OSNet from ONNX/PyTorch to TRT engines.

Usage:
    python -m forensics.trt_export
"""
import os
import sys
import logging
import numpy as np
from pathlib import Path

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s %(levelname)s: %(message)s')

def check_tensorrt():
    """Verify TensorRT is available."""
    try:
        import tensorrt as trt
        logger.info(f"TensorRT version: {trt.__version__}")
        return trt
    except ImportError:
        logger.error("TensorRT not found. Install: pip install tensorrt")
        sys.exit(1)

def build_engine_from_onnx(trt, onnx_path: str, engine_path: str,
                           fp16: bool = True,
                           dynamic_batch: bool = False,
                           min_batch: int = 1, opt_batch: int = 1, max_batch: int = 1,
                           workspace_gb: float = 2.0):
    """Build a TRT engine from ONNX model."""
    TRT_LOGGER = trt.Logger(trt.Logger.WARNING)
    
    builder = trt.Builder(TRT_LOGGER)
    network = builder.create_network(1 << int(trt.NetworkDefinitionCreationFlag.EXPLICIT_BATCH))
    parser = trt.OnnxParser(network, TRT_LOGGER)
    
    # Parse ONNX
    logger.info(f"Parsing ONNX: {onnx_path}")
    with open(onnx_path, 'rb') as f:
        if not parser.parse(f.read()):
            for i in range(parser.num_errors):
                logger.error(f"ONNX Parse Error: {parser.get_error(i)}")
            return False
    
    # Build config
    config = builder.create_builder_config()
    config.set_memory_pool_limit(trt.MemoryPoolType.WORKSPACE, int(workspace_gb * (1 << 30)))
    
    if fp16 and builder.platform_has_fast_fp16:
        config.set_flag(trt.BuilderFlag.FP16)
        logger.info("FP16 mode enabled")
    
    # Dynamic batch profiles
    if dynamic_batch:
        profile = builder.create_optimization_profile()
        input_tensor = network.get_input(0)
        input_shape = input_tensor.shape  # e.g., (-1, 3, 256, 128)
        
        min_shape = list(input_shape)
        opt_shape = list(input_shape)
        max_shape = list(input_shape)
        min_shape[0] = min_batch
        opt_shape[0] = opt_batch
        max_shape[0] = max_batch
        
        profile.set_shape(input_tensor.name, tuple(min_shape), tuple(opt_shape), tuple(max_shape))
        config.add_optimization_profile(profile)
        logger.info(f"Dynamic batch: min={min_batch}, opt={opt_batch}, max={max_batch}")
    
    # Build
    logger.info(f"Building TRT engine (this may take several minutes)...")
    serialized_engine = builder.build_serialized_network(network, config)
    
    if serialized_engine is None:
        logger.error("Engine build failed!")
        return False
    
    with open(engine_path, 'wb') as f:
        f.write(serialized_engine)
    
    logger.info(f"Engine saved: {engine_path} ({os.path.getsize(engine_path) / 1e6:.1f} MB)")
    return True

def export_osnet_to_onnx(onnx_path: str):
    """Export OSNet x1_0 from PyTorch to ONNX."""
    import torch
    import torchreid
    
    logger.info("Exporting OSNet x1_0 to ONNX...")
    model = torchreid.models.build_model(name='osnet_x1_0', num_classes=1000, pretrained=True)
    model.eval()
    
    dummy_input = torch.randn(1, 3, 256, 128)
    
    torch.onnx.export(
        model, dummy_input, onnx_path,
        input_names=['input'],
        output_names=['features'],
        dynamic_axes={'input': {0: 'batch'}, 'features': {0: 'batch'}},
        opset_version=17,
        do_constant_folding=True
    )
    logger.info(f"OSNet ONNX saved: {onnx_path}")

def warmup_engine(engine_path: str, input_shape: tuple):
    """Run a warm-up pass on a TRT engine."""
    import tensorrt as trt
    
    TRT_LOGGER = trt.Logger(trt.Logger.WARNING)
    runtime = trt.Runtime(TRT_LOGGER)
    
    with open(engine_path, 'rb') as f:
        engine = runtime.deserialize_cuda_engine(f.read())
    
    context = engine.create_execution_context()
    
    # Allocate dummy I/O
    import torch
    dummy_input = torch.randn(*input_shape, device='cuda', dtype=torch.float32)
    
    # Get output shape
    output_shape = engine.get_tensor_shape(engine.get_tensor_name(1))
    if output_shape[0] == -1:
        output_shape = list(output_shape)
        output_shape[0] = input_shape[0]
    dummy_output = torch.empty(*output_shape, device='cuda', dtype=torch.float32)
    
    # Run 3 warm-up passes
    for i in range(3):
        context.set_tensor_address(engine.get_tensor_name(0), dummy_input.data_ptr())
        context.set_tensor_address(engine.get_tensor_name(1), dummy_output.data_ptr())
        context.execute_async_v3(torch.cuda.current_stream().cuda_stream)
        torch.cuda.synchronize()
    
    logger.info(f"Warm-up complete for {engine_path}")

def main():
    weights_dir = Path(__file__).resolve().parent / 'ai_core' / 'weights'
    antelopev2_dir = weights_dir / 'models' / 'antelopev2'
    
    trt = check_tensorrt()
    
    results = {}
    
    # 1. SCRFD (face detection)
    scrfd_onnx = antelopev2_dir / 'scrfd_10g_bnkps.onnx'
    scrfd_engine = antelopev2_dir / 'scrfd_10g_bnkps.engine'
    if scrfd_onnx.exists() and not scrfd_engine.exists():
        logger.info("=== Exporting SCRFD to TRT FP16 ===")
        ok = build_engine_from_onnx(trt, str(scrfd_onnx), str(scrfd_engine), fp16=True)
        results['SCRFD'] = '✅' if ok else '❌'
    elif scrfd_engine.exists():
        logger.info(f"SCRFD engine already exists: {scrfd_engine}")
        results['SCRFD'] = '✅ (cached)'
    else:
        logger.warning(f"SCRFD ONNX not found: {scrfd_onnx}")
        results['SCRFD'] = '⏭️ skipped'
    
    # 2. GlintR100 / ArcFace (face embedding) — FP16 is safe for embeddings
    arcface_onnx = antelopev2_dir / 'glintr100.onnx'
    arcface_engine = antelopev2_dir / 'glintr100.engine'
    if arcface_onnx.exists() and not arcface_engine.exists():
        logger.info("=== Exporting ArcFace (GlintR100) to TRT FP16 ===")
        ok = build_engine_from_onnx(trt, str(arcface_onnx), str(arcface_engine), fp16=True)
        results['ArcFace'] = '✅' if ok else '❌'
    elif arcface_engine.exists():
        logger.info(f"ArcFace engine already exists: {arcface_engine}")
        results['ArcFace'] = '✅ (cached)'
    else:
        logger.warning(f"ArcFace ONNX not found: {arcface_onnx}")
        results['ArcFace'] = '⏭️ skipped'

    # 3. OSNet (body ReID) — Export PyTorch→ONNX→TRT
    osnet_onnx = weights_dir / 'osnet_x1_0.onnx'
    osnet_engine = weights_dir / 'osnet_x1_0.engine'
    if not osnet_engine.exists():
        if not osnet_onnx.exists():
            logger.info("=== Exporting OSNet to ONNX ===")
            export_osnet_to_onnx(str(osnet_onnx))
        
        logger.info("=== Exporting OSNet to TRT FP16 (dynamic batch) ===")
        ok = build_engine_from_onnx(
            trt, str(osnet_onnx), str(osnet_engine),
            fp16=True, dynamic_batch=True,
            min_batch=1, opt_batch=5, max_batch=20
        )
        results['OSNet'] = '✅' if ok else '❌'
    else:
        logger.info(f"OSNet engine already exists: {osnet_engine}")
        results['OSNet'] = '✅ (cached)'
    
    # Summary
    print("\n" + "="*50)
    print("TRT EXPORT SUMMARY")
    print("="*50)
    for model, status in results.items():
        print(f"  {model:12s} : {status}")
    print("="*50)

if __name__ == '__main__':
    main()
