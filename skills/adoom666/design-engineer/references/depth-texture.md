# Depth & Texture Reference

Flat design is dead. Modern interfaces have depth, tactility, and atmosphere.

## Shadows

Don't use default CSS shadows. Layer multiple shadows for realistic diffusion.

### Layered Shadow Pattern
```css
.card {
  box-shadow:
    /* Layer 1: Tight, dark, ambient occlusion */
    0 1px 2px rgba(0, 0, 0, 0.07),
    /* Layer 2: Medium diffusion */
    0 4px 8px rgba(0, 0, 0, 0.07),
    /* Layer 3: Large, soft, atmospheric */
    0 16px 32px rgba(0, 0, 0, 0.07);
}
```

### Elevation Levels
```css
/* Level 1: Subtle lift */
--shadow-sm: 0 1px 2px rgba(0,0,0,0.05);

/* Level 2: Cards */
--shadow-md:
  0 1px 3px rgba(0,0,0,0.06),
  0 4px 12px rgba(0,0,0,0.08);

/* Level 3: Dropdowns, popovers */
--shadow-lg:
  0 2px 4px rgba(0,0,0,0.06),
  0 8px 24px rgba(0,0,0,0.12);

/* Level 4: Modals, dialogs */
--shadow-xl:
  0 4px 8px rgba(0,0,0,0.08),
  0 16px 48px rgba(0,0,0,0.16);
```

### Colored Shadows
Match shadow color to element for realism:

```css
.card-primary {
  background: #3b82f6;
  box-shadow:
    0 4px 12px rgba(59, 130, 246, 0.3),
    0 8px 24px rgba(59, 130, 246, 0.2);
}
```

## Glass & Blur

Use `backdrop-filter: blur()` for context and layering.

```css
.glass-panel {
  background: rgba(255, 255, 255, 0.1);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border: 1px solid rgba(255, 255, 255, 0.2);
}

/* Dark mode glass */
.glass-dark {
  background: rgba(0, 0, 0, 0.4);
  backdrop-filter: blur(16px);
  border: 1px solid rgba(255, 255, 255, 0.1);
}
```

## Noise & Grain

Subtle noise (3-5% opacity) reduces color banding and adds analog feel.

### SVG Noise Filter
```html
<svg class="absolute inset-0 w-full h-full pointer-events-none opacity-[0.03]">
  <filter id="noise">
    <feTurbulence type="fractalNoise" baseFrequency="0.8" numOctaves="4" stitchTiles="stitch"/>
  </filter>
  <rect width="100%" height="100%" filter="url(#noise)"/>
</svg>
```

### CSS Background Image
```css
.noise-overlay {
  background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.7' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E");
  opacity: 0.04;
  pointer-events: none;
}
```

## Gradients

Use subtle mesh/aurora gradients instead of solid colors.

### Mesh Gradient
```css
.mesh-bg {
  background:
    radial-gradient(at 40% 20%, hsla(210, 100%, 70%, 0.3) 0px, transparent 50%),
    radial-gradient(at 80% 80%, hsla(280, 100%, 70%, 0.2) 0px, transparent 50%),
    radial-gradient(at 10% 80%, hsla(340, 100%, 70%, 0.2) 0px, transparent 50%),
    hsl(220, 20%, 10%);
}
```

### Aurora/Northern Lights
```css
.aurora-bg {
  background: linear-gradient(
    135deg,
    hsl(220, 60%, 20%) 0%,
    hsl(280, 60%, 25%) 25%,
    hsl(320, 60%, 20%) 50%,
    hsl(260, 60%, 25%) 75%,
    hsl(220, 60%, 20%) 100%
  );
  background-size: 400% 400%;
  animation: aurora 15s ease infinite;
}

@keyframes aurora {
  0%, 100% { background-position: 0% 50%; }
  50% { background-position: 100% 50%; }
}
```

### Glow Effects
```css
.neon-glow {
  box-shadow:
    0 0 5px currentColor,
    0 0 20px currentColor,
    0 0 40px currentColor;
}

.text-glow {
  text-shadow:
    0 0 10px currentColor,
    0 0 20px currentColor;
}
```

## Tailwind Implementation

```html
<!-- Layered shadow -->
<div class="shadow-sm shadow-black/5 [box-shadow:0_4px_12px_rgba(0,0,0,0.08)]">

<!-- Glass -->
<div class="bg-white/10 backdrop-blur-xl border border-white/20">

<!-- Gradient background -->
<div class="bg-gradient-to-br from-blue-500/20 via-purple-500/10 to-pink-500/20">
```
