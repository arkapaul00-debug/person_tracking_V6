"""
Async DAG Pipeline Package — Stage-Based Video Analytics Execution Engine.

Replaces the monolithic _run_loop in StreamProcessor with independent,
asynchronous stages connected by backpressure-aware queues.

Pipeline stages:
    Ingest → Decode → Preprocess → Detect → Track → Recognize → Analytics → Event → Evidence
"""
