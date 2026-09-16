# Spacing & Layout Reference

Whitespace is an active design element, not just empty space.

## Spacing Scale

Use a consistent 4px base scale:

| Token | Value | Use Case |
|:---|:---|:---|
| `--space-1` | 4px | Component internals, icon gaps |
| `--space-2` | 8px | Tight element spacing |
| `--space-3` | 12px | Form element gaps |
| `--space-4` | 16px | Standard padding |
| `--space-6` | 24px | Card padding |
| `--space-8` | 32px | Layout gaps |
| `--space-12` | 48px | Section separation |
| `--space-16` | 64px | Major section breaks |
| `--space-24` | 96px | Hero spacing |
| `--space-32` | 128px | Page section dividers |

## Breaking the Grid

### Asymmetry
Center alignment is safe but boring. Offset elements to create dynamic tension.

```jsx
// Instead of centered hero
<div className="text-center mx-auto max-w-2xl">

// Try asymmetric layout
<div className="grid grid-cols-12 gap-8">
  <div className="col-span-7 col-start-2">
    {/* Content offset left */}
  </div>
</div>
```

### Overlap
Let elements break out of their containers:

```jsx
// Image breaking out of container
<div className="relative">
  <div className="container mx-auto">
    <p>Content here</p>
  </div>
  <img
    className="absolute right-0 top-1/2 -translate-y-1/2 w-1/2 translate-x-1/4"
    src={image}
  />
</div>

// Text overlapping image
<div className="relative">
  <img className="w-full" src={image} />
  <h2 className="absolute bottom-0 left-8 translate-y-1/2 bg-background px-4 py-2">
    Title overlapping
  </h2>
</div>
```

### Rhythm
Consistent vertical rhythm creates visual harmony:

```css
/* Vertical rhythm with consistent spacing */
.section { margin-bottom: 96px; }
.section-heading { margin-bottom: 48px; }
.content-block { margin-bottom: 32px; }
.paragraph { margin-bottom: 24px; }
```

## Grid Patterns

### 12-Column Base Grid
```jsx
<div className="grid grid-cols-12 gap-4 md:gap-8">
  {/* Flexible column spans */}
</div>
```

### Asymmetric Sidebar
```jsx
<div className="grid grid-cols-12 gap-8">
  <main className="col-span-8">Main content</main>
  <aside className="col-span-4">Sidebar</aside>
</div>
```

### Bento Grid
```jsx
<div className="grid grid-cols-4 grid-rows-3 gap-4">
  <div className="col-span-2 row-span-2">Large</div>
  <div>Small</div>
  <div>Small</div>
  <div className="col-span-2">Wide</div>
</div>
```

### Auto-fit Responsive Grid
```jsx
<div className="grid grid-cols-[repeat(auto-fit,minmax(280px,1fr))] gap-6">
  {/* Cards automatically wrap */}
</div>
```

## Container Widths

```css
--container-sm: 640px;   /* Narrow content (blog) */
--container-md: 768px;   /* Standard content */
--container-lg: 1024px;  /* Wide content */
--container-xl: 1280px;  /* Dashboard layouts */
--container-2xl: 1536px; /* Full-width apps */
```

## Common Layout Patterns

### Full-Bleed with Contained Content
```jsx
<section className="w-full bg-muted py-24">
  <div className="container mx-auto px-4 max-w-5xl">
    {/* Content stays contained, background bleeds */}
  </div>
</section>
```

### Split Screen
```jsx
<div className="grid grid-cols-1 lg:grid-cols-2 min-h-screen">
  <div className="flex items-center justify-center p-8">
    {/* Left side */}
  </div>
  <div className="flex items-center justify-center p-8 bg-muted">
    {/* Right side */}
  </div>
</div>
```

### Sticky Sidebar
```jsx
<div className="flex gap-8">
  <aside className="w-64 shrink-0">
    <div className="sticky top-24">
      {/* Sidebar content */}
    </div>
  </aside>
  <main className="flex-1">
    {/* Scrolling content */}
  </main>
</div>
```
