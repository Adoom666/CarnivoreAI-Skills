# Style Archetypes Reference

Choose ONE archetype and commit fully. Mixing archetypes creates visual confusion.

## Quick Reference Table

| Archetype | Emotion | Typography | Visuals |
|:---|:---|:---|:---|
| **Swiss/International** | Order, Clarity, Trust | Sans-serif, tight tracking, large scale | Grids, asymmetry, high contrast, minimal |
| **Digital Brutalism** | Raw, Honest, Edgy | Monospace, system fonts, unconventional sizing | Borders, neo-brutal shadows, stark colors, no gradients |
| **Soft Pop/Clay** | Friendly, Playful, Easy | Rounded sans (Nunito, Quicksand) | Pastels, soft shadows, large radii, bounce animations |
| **Glassmorphism** | Modern, Tech, Sleek | Clean sans (Inter, Geist) | Blurs, translucency, subtle gradients, noise/grain |
| **Dark Future** | Premium, Exclusive, Tech | Extended sans or technical mono | Dark mode only, neon accents, glow effects, linear gradients |
| **Editorial/Luxury** | Sophisticated, Timeless | Serif display + clean sans | Centered layouts, generous whitespace, muted palettes |

## Detailed Archetype Specifications

### Swiss/International
```css
/* Typography */
font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
letter-spacing: -0.02em; /* tight */
font-size: clamp(2rem, 5vw, 4rem); /* large scale */

/* Layout */
display: grid;
grid-template-columns: repeat(12, 1fr);
/* Asymmetric placement within grid */

/* Colors */
--bg: #ffffff;
--fg: #000000;
--accent: #ff0000; /* single strong accent */
```

### Digital Brutalism
```css
/* Typography */
font-family: 'IBM Plex Mono', 'Courier New', monospace;
text-transform: uppercase;

/* Borders instead of shadows */
border: 3px solid #000;
box-shadow: 8px 8px 0 #000; /* neo-brutal offset shadow */

/* Colors - stark, no gradients */
--bg: #ffffff;
--accent: #ff3366;
--brutal-shadow: #000000;
```

### Soft Pop/Clay
```css
/* Typography */
font-family: 'Nunito', 'Quicksand', sans-serif;
font-weight: 600;

/* Soft everything */
border-radius: 24px;
box-shadow: 0 4px 20px rgba(0,0,0,0.08);

/* Animation */
transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1); /* bounce */

/* Colors - pastels */
--bg: #fef6f0;
--accent: #ff9a9e;
```

### Glassmorphism
```css
/* Glass effect */
background: rgba(255, 255, 255, 0.1);
backdrop-filter: blur(20px);
-webkit-backdrop-filter: blur(20px);
border: 1px solid rgba(255, 255, 255, 0.2);

/* Subtle gradient backgrounds */
background: linear-gradient(135deg, rgba(255,255,255,0.1), rgba(255,255,255,0.05));

/* Noise overlay (SVG pattern at 3-5% opacity) */
```

### Dark Future
```css
/* Always dark */
--bg: #0a0a0f;
--surface: #12121a;

/* Neon accents with glow */
--accent: #00ffff;
--glow: 0 0 20px rgba(0, 255, 255, 0.5);

/* Typography */
font-family: 'Space Grotesk', 'Orbitron', sans-serif;
text-transform: uppercase;
letter-spacing: 0.1em;
```

### Editorial/Luxury
```css
/* Typography pairing */
--font-display: 'Cormorant Garamond', serif;
--font-body: 'Lato', sans-serif;

/* Generous whitespace */
padding: 8rem 4rem;
line-height: 1.8;

/* Muted palette */
--bg: #f8f7f4;
--fg: #2c2c2c;
--accent: #8b7355;
```
