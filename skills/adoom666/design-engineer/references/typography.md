# Typography Reference

Typography is 90% of web design. Never use a single weight of Inter for everything.

## Pairing Strategies

### The Contrast Pair
Strong display font for headings + highly legible sans for body.

| Display (Headings) | Body |
|:---|:---|
| Playfair Display | Lato |
| Cormorant Garamond | Source Sans Pro |
| Libre Baskerville | Open Sans |

### The Tech Pair
Geometric sans for headings + monospace for data/labels.

| Headings | UI Elements/Data |
|:---|:---|
| Space Grotesk | JetBrains Mono |
| Outfit | Fira Code |
| Orbitron | IBM Plex Mono |

### The Workhorse
Variable font with huge weight range (Thin for elegance, Black for impact).

| Font | Weight Range |
|:---|:---|
| Inter | 100-900 |
| Roboto Flex | 100-1000 |
| Plus Jakarta Sans | 200-800 |

## Technical Execution

### Fluid Typography with clamp()
```css
/* Headings */
h1 { font-size: clamp(2rem, 5vw + 1rem, 4rem); }
h2 { font-size: clamp(1.5rem, 3vw + 0.5rem, 2.5rem); }
h3 { font-size: clamp(1.25rem, 2vw + 0.5rem, 1.75rem); }

/* Body */
body { font-size: clamp(1rem, 1vw + 0.5rem, 1.125rem); }
```

### Line Height (Leading)
```css
/* Tighter for headings */
h1, h2, h3 { line-height: 1.1; }

/* Looser for body text */
p, li { line-height: 1.6; }

/* Very loose for small text */
.caption { line-height: 1.8; }
```

### Letter Spacing (Tracking)
```css
/* Tighten large headings */
h1 { letter-spacing: -0.02em; }

/* Normal for body */
p { letter-spacing: 0; }

/* Loosen small caps and labels */
.label {
  letter-spacing: 0.05em;
  text-transform: uppercase;
  font-size: 0.75rem;
}
```

## Tailwind Implementation
```html
<!-- Fluid heading -->
<h1 class="text-3xl md:text-5xl lg:text-6xl font-bold tracking-tight leading-tight">

<!-- Body text -->
<p class="text-base md:text-lg leading-relaxed">

<!-- Label/caption -->
<span class="text-xs uppercase tracking-wider font-medium text-muted-foreground">
```
