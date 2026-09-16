# Tailwind CSS v4 Reference

Modern Tailwind workflow using CSS variables and the @theme directive.

## Theme Configuration (index.css)

Use CSS variables for all design tokens:

```css
@import "tailwindcss";

@theme inline {
  /* Colors */
  --color-background: hsl(0 0% 100%);
  --color-foreground: hsl(222 47% 11%);
  --color-muted: hsl(210 40% 96%);
  --color-muted-foreground: hsl(215 16% 47%);
  --color-primary: hsl(222 47% 11%);
  --color-primary-foreground: hsl(210 40% 98%);
  --color-accent: hsl(210 40% 96%);
  --color-accent-foreground: hsl(222 47% 11%);
  --color-destructive: hsl(0 84% 60%);
  --color-border: hsl(214 32% 91%);

  /* Typography */
  --font-display: "Outfit", sans-serif;
  --font-body: "Inter", sans-serif;
  --font-mono: "JetBrains Mono", monospace;

  /* Spacing */
  --spacing-section: 6rem;
  --spacing-card: 1.5rem;

  /* Radii */
  --radius-sm: 0.25rem;
  --radius-md: 0.5rem;
  --radius-lg: 1rem;
  --radius-card: 0.75rem;

  /* Shadows */
  --shadow-card:
    0 1px 3px rgba(0, 0, 0, 0.06),
    0 4px 12px rgba(0, 0, 0, 0.08);

  /* Animation */
  --animate-fade-in: fade-in 0.5s ease-out;
  --animate-slide-up: slide-up 0.4s ease-out;

  @keyframes fade-in {
    from { opacity: 0; }
    to { opacity: 1; }
  }

  @keyframes slide-up {
    from {
      opacity: 0;
      transform: translateY(20px);
    }
    to {
      opacity: 1;
      transform: translateY(0);
    }
  }
}

/* Dark mode overrides */
.dark {
  --color-background: hsl(222 47% 6%);
  --color-foreground: hsl(210 40% 98%);
  --color-muted: hsl(217 33% 17%);
  --color-muted-foreground: hsl(215 20% 65%);
  --color-border: hsl(217 33% 20%);
}
```

## Component Classes

```css
@layer components {
  .btn-primary {
    @apply bg-primary text-primary-foreground px-4 py-2 font-medium
           transition-all duration-200 hover:opacity-90 active:scale-95;
  }

  .card {
    @apply bg-background border border-border rounded-card p-card
           shadow-card transition-all duration-200 hover:shadow-lg;
  }

  .input {
    @apply w-full bg-background border border-border rounded-md px-3 py-2
           text-foreground placeholder:text-muted-foreground
           focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary;
  }
}
```

## Utility Patterns

### Container with Full-Bleed
```html
<div class="container mx-auto px-4 sm:px-6 lg:px-8 max-w-7xl">
```

### Responsive Typography
```html
<h1 class="text-3xl sm:text-4xl md:text-5xl lg:text-6xl font-display font-bold tracking-tight">
```

### Flexbox Patterns
```html
<!-- Centered content -->
<div class="flex items-center justify-center min-h-screen">

<!-- Space between with wrap -->
<div class="flex flex-wrap items-center justify-between gap-4">

<!-- Stack on mobile, row on desktop -->
<div class="flex flex-col md:flex-row gap-4">
```

### Grid Patterns
```html
<!-- Responsive grid -->
<div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">

<!-- Sidebar layout -->
<div class="grid grid-cols-1 lg:grid-cols-[280px_1fr] gap-8">

<!-- Auto-fit grid -->
<div class="grid grid-cols-[repeat(auto-fit,minmax(300px,1fr))] gap-6">
```

### Hover/Focus States
```html
<button class="
  transition-all duration-200
  hover:bg-primary/90 hover:shadow-lg hover:-translate-y-0.5
  focus:outline-none focus:ring-2 focus:ring-primary/50
  active:scale-95
">
```

### Layered Shadows
```html
<div class="shadow-sm shadow-black/5 [box-shadow:0_4px_12px_rgba(0,0,0,0.08),0_1px_3px_rgba(0,0,0,0.06)]">
```

### Glass Effect
```html
<div class="bg-background/80 backdrop-blur-xl border border-border/50">
```

### Gradient Background
```html
<div class="bg-gradient-to-br from-primary/10 via-transparent to-accent/10">
```

## Custom Arbitrary Values

```html
<!-- Custom animation -->
<div class="animate-[fade-in_0.5s_ease-out]">

<!-- Custom shadow -->
<div class="shadow-[0_4px_20px_rgba(0,0,0,0.15)]">

<!-- Custom grid -->
<div class="grid-cols-[200px_1fr_100px]">

<!-- Custom clamp -->
<h1 class="text-[clamp(2rem,5vw,4rem)]">
```
