// ═══ FILE: src/pages/Landing.tsx ═══
import React, { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';

const Landing: React.FC = () => {
  const navigate = useNavigate();
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [time, setTime] = useState(new Date());
  const [glitching, setGlitching] = useState(false);
  const [taglineIndex, setTaglineIndex] = useState(0);

  const taglines = [
    "TOTAL VISION. TOTAL CONTROL.",
    "AI THAT NEVER BLINKS.",
    "EVERY THREAT. IDENTIFIED. NEUTRALIZED.",
    "PROTECTING WHAT MATTERS MOST."
  ];

  // Stats Counters
  const [cameras, setCameras] = useState(0);
  const [threats, setThreats] = useState(0);
  const [uptime, setUptime] = useState(0);
  const [users, setUsers] = useState(0);
  const [confidence, setConfidence] = useState(0);

  useEffect(() => {
    // Clock
    const timer = setInterval(() => setTime(new Date()), 1000);
    
    // Glitch effect
    const glitchTimer = setInterval(() => {
      setGlitching(true);
      setTimeout(() => setGlitching(false), 200 + Math.random() * 100);
    }, 4000 + Math.random() * 2000);

    // Tagline rotation
    const taglineTimer = setInterval(() => {
      setTaglineIndex(prev => (prev + 1) % taglines.length);
    }, 3000);

    // Stats animation
    let startTimestamp: number | null = null;
    const duration = 1500;
    
    const step = (timestamp: number) => {
      if (!startTimestamp) startTimestamp = timestamp;
      const progress = Math.min((timestamp - startTimestamp) / duration, 1);
      
      // Easing out function
      const easeOut = 1 - Math.pow(1 - progress, 3);
      
      setCameras(Math.floor(easeOut * 24));
      setThreats(Math.floor(easeOut * 1847));
      setUptime(easeOut * 99.97);
      setUsers(Math.floor(easeOut * 12));
      setConfidence(easeOut * 98.3);

      if (progress < 1) {
        requestAnimationFrame(step);
      }
    };
    requestAnimationFrame(step);

    return () => {
      clearInterval(timer);
      clearInterval(glitchTimer);
      clearInterval(taglineTimer);
    };
  }, []);

  // Canvas animations (Matrix Rain + Particles)
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    let animationFrameId: number;
    let particles: { x: number, y: number, vx: number, vy: number }[] = [];
    const numParticles = 80;
    
    // Matrix rain
    const fontSize = 12;
    let columns = Math.floor(window.innerWidth / fontSize);
    let drops: number[] = [];
    for (let x = 0; x < columns; x++) {
      drops[x] = Math.random() * -100; // Start above screen
    }

    const resize = () => {
      canvas.width = window.innerWidth;
      canvas.height = window.innerHeight;
      columns = Math.floor(canvas.width / fontSize);
      drops = [];
      for (let x = 0; x < columns; x++) {
        drops[x] = Math.random() * -100;
      }
      // Re-init particles on resize to keep them within bounds
      particles = [];
      for (let i = 0; i < numParticles; i++) {
        particles.push({
          x: Math.random() * canvas.width,
          y: Math.random() * canvas.height,
          vx: (Math.random() - 0.5) * 0.5,
          vy: (Math.random() - 0.5) * 0.5
        });
      }
    };
    window.addEventListener('resize', resize);
    resize();

    const draw = () => {
      // Fade background for trail effect
      ctx.fillStyle = 'rgba(2, 8, 16, 0.1)';
      ctx.fillRect(0, 0, canvas.width, canvas.height);

      // --- Matrix Rain ---
      ctx.fillStyle = 'rgba(0, 212, 255, 0.15)';
      ctx.font = `${fontSize}px monospace`;
      
      for (let i = 0; i < drops.length; i++) {
        const text = Math.random() > 0.5 ? '1' : '0';
        ctx.fillText(text, i * fontSize, drops[i] * fontSize);
        
        if (drops[i] * fontSize > canvas.height && Math.random() > 0.975) {
          drops[i] = 0;
        }
        // Different falling speeds
        drops[i] += (0.5 + Math.random() * 0.5);
      }

      // --- Particles ---
      particles.forEach(p => {
        p.x += p.vx;
        p.y += p.vy;

        // Bounce
        if (p.x < 0 || p.x > canvas.width) p.vx *= -1;
        if (p.y < 0 || p.y > canvas.height) p.vy *= -1;

        ctx.beginPath();
        ctx.arc(p.x, p.y, 1.5, 0, Math.PI * 2);
        ctx.fillStyle = 'rgba(0, 212, 255, 0.4)';
        ctx.fill();

        // Connect particles
        particles.forEach(p2 => {
          const dx = p.x - p2.x;
          const dy = p.y - p2.y;
          const dist = Math.sqrt(dx * dx + dy * dy);
          if (dist < 120) {
            ctx.beginPath();
            ctx.moveTo(p.x, p.y);
            ctx.lineTo(p2.x, p2.y);
            ctx.strokeStyle = `rgba(0, 212, 255, ${0.15 * (1 - dist/120)})`;
            ctx.lineWidth = 1;
            ctx.stroke();
          }
        });
      });

      animationFrameId = requestAnimationFrame(draw);
    };
    draw();

    return () => {
      window.removeEventListener('resize', resize);
      cancelAnimationFrame(animationFrameId);
    };
  }, []);

  return (
    <div style={{ position: 'relative', width: '100vw', height: '100vh', overflow: 'hidden', background: '#020810' }}>
      {/* Background Layers */}
      <canvas ref={canvasRef} style={{ position: 'absolute', top: 0, left: 0, zIndex: 0 }} />
      
      {/* Animated Grid */}
      <div style={{
        position: 'absolute', top: 0, left: 0, width: '100%', height: '100%',
        backgroundImage: 'linear-gradient(rgba(0, 255, 200, 0.06) 1px, transparent 1px), linear-gradient(90deg, rgba(0, 255, 200, 0.06) 1px, transparent 1px)',
        backgroundSize: '40px 40px',
        transform: 'perspective(500px) rotateX(60deg)',
        transformOrigin: 'bottom',
        zIndex: 0,
        pointerEvents: 'none',
      }}></div>

      {/* Scan Line */}
      <div className="scan-line" />

      {/* Decorative Brackets */}
      <div className="corner-bracket tl"></div>
      <div className="corner-bracket tr"></div>
      <div className="corner-bracket bl"></div>
      <div className="corner-bracket br"></div>

      {/* Side Panels */}
      <div style={{
        position: 'absolute', left: 16, top: '20%', bottom: '20%', width: 20, overflow: 'hidden',
        color: 'rgba(0, 212, 255, 0.2)', fontSize: '0.6rem', fontFamily: 'monospace', lineHeight: 1.5, zIndex: 1, writingMode: 'vertical-rl', transform: 'rotate(180deg)'
      }}>
        {Array.from({length: 40}).map((_, i) => <span key={i}>FF A0 3C 87 2E 99 B4 1D </span>)}
      </div>
      <div style={{
        position: 'absolute', right: 16, top: '20%', bottom: '20%', width: 20, overflow: 'hidden',
        color: 'rgba(0, 212, 255, 0.2)', fontSize: '0.6rem', fontFamily: 'monospace', lineHeight: 1.5, zIndex: 1, writingMode: 'vertical-rl'
      }}>
        {Array.from({length: 40}).map((_, i) => <span key={i}>2E 99 B4 1D FF A0 3C 87 </span>)}
      </div>

      {/* Warning Strips Bottom */}
      <div style={{
        position: 'absolute', bottom: 0, left: 0, width: '100%', height: 4, zIndex: 5,
        background: 'repeating-linear-gradient(45deg, #000, #000 10px, #ffaa00 10px, #ffaa00 20px)'
      }}></div>

      {/* Content Container */}
      <div style={{ position: 'relative', zIndex: 10, display: 'flex', flexDirection: 'column', height: '100%' }}>
        
        {/* Header Bar */}
        <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '24px 40px' }}>
          <div style={{ flex: 1 }}>
            <h1 className={`glitch-text ${glitching ? 'glitching' : ''}`} data-text="SENTINEL" 
                style={{ margin: 0, fontSize: '2rem', color: '#00d4ff', fontFamily: 'Orbitron, monospace', fontWeight: 900 }}>
              SENTINEL
            </h1>
          </div>
          
          <div style={{ flex: 1, textAlign: 'center', color: '#00cc88', fontFamily: 'monospace', fontSize: '0.9rem', letterSpacing: '2px' }}>
            <span className="pulse-dot" style={{ marginRight: '8px' }}></span>
            [ SYSTEM STATUS: ONLINE ]
          </div>
          
          <div style={{ flex: 1, textAlign: 'right', color: '#00d4ff', fontFamily: 'monospace' }}>
            <div style={{ fontSize: '1.2rem', fontWeight: 'bold' }}>
              {time.toLocaleTimeString('en-GB', { hour12: false })}
            </div>
            <div style={{ fontSize: '0.8rem', opacity: 0.8 }}>
              {time.toLocaleDateString('en-GB', { day: '2-digit', month: '2-digit', year: 'numeric' }).replace(/\//g, '.')}
            </div>
          </div>
        </header>

        {/* Stats Bar */}
        <div style={{ display: 'flex', justifyContent: 'center', gap: '20px', padding: '0 40px', marginTop: '20px' }}>
          {[
            { label: 'CAMERAS ONLINE', value: cameras },
            { label: 'THREATS DETECTED', value: threats.toLocaleString() },
            { label: 'UPTIME', value: uptime.toFixed(2) + '%' },
            { label: 'USERS ACTIVE', value: users },
            { label: 'AI CONFIDENCE', value: confidence.toFixed(1) + '%' }
          ].map((stat, i) => (
            <div key={i} style={{
              border: '1px solid rgba(0, 212, 255, 0.3)',
              background: 'rgba(0, 212, 255, 0.04)',
              padding: '12px 24px',
              textAlign: 'center',
              minWidth: '180px'
            }}>
              <div style={{ fontSize: '0.65rem', color: '#7a8db0', letterSpacing: '0.1em', marginBottom: '8px' }}>{stat.label}</div>
              <div style={{ fontSize: '1.5rem', color: '#00d4ff', fontFamily: 'Share Tech Mono, monospace' }}>{stat.value}</div>
            </div>
          ))}
        </div>

        {/* Center Hero */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center' }}>
          <h2 style={{
            fontSize: 'clamp(3rem, 8vw, 7rem)',
            fontFamily: 'Orbitron, monospace',
            fontWeight: 'bold',
            color: 'white',
            textShadow: '0 0 30px #00d4ff, 0 0 60px #00d4ff',
            margin: 0,
            lineHeight: 1
          }}>
            SENTINEL PRO
          </h2>
          <div style={{ color: '#00d4ff', fontFamily: 'monospace', fontSize: '1.2rem', marginTop: '10px', letterSpacing: '3px' }}>
            ENTERPRISE AI-POWERED SURVEILLANCE SYSTEM
          </div>
          
          <div style={{ height: '40px', marginTop: '40px', color: '#e8eaf2', fontSize: '1.1rem', letterSpacing: '2px', transition: 'opacity 0.5s' }}>
            {taglines[taglineIndex]}
          </div>

          <div style={{ display: 'flex', gap: '40px', marginTop: '60px' }}>
            <button className="btn-sentinel btn-admin" onClick={() => navigate('/admin/login')}>
              <span style={{ fontSize: '1.2rem' }}>🛡️</span> ADMIN PANEL
              <div className="btn-scan"></div>
            </button>
            <button className="btn-sentinel btn-user" onClick={() => navigate('/login')}>
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path><circle cx="12" cy="7" r="4"></circle></svg>
              <span style={{ marginLeft: '8px' }}>USER PANEL</span>
              <div className="btn-scan"></div>
            </button>
          </div>
        </div>

        {/* Bottom System Info Bar */}
        <footer style={{ padding: '16px 40px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: 'rgba(2, 8, 16, 0.8)' }}>
          <div style={{ color: '#ff3b3b', fontSize: '0.75rem', fontFamily: 'monospace', letterSpacing: '1px' }}>
            [ CLASSIFIED — AUTHORIZED ACCESS ONLY ] <span style={{ animation: 'pulse 1s infinite' }}>▮</span>
          </div>
          
          <div style={{ display: 'flex', gap: '2px', alignItems: 'flex-end', height: '20px' }}>
            {Array.from({length: 40}).map((_, i) => (
              <div key={i} style={{
                width: '2px',
                background: '#00d4ff',
                opacity: 0.6,
                height: `${Math.random() * 100}%`,
                animation: `pulse ${0.5 + Math.random()}s infinite alternate`
              }}></div>
            ))}
          </div>
          
          <div style={{ color: '#7a8db0', fontSize: '0.75rem', fontFamily: 'monospace' }}>
            v2.0.0 | BUILD 20250628
          </div>
        </footer>

      </div>
    </div>
  );
};

export default Landing;
