# Motion & Animation Reference

Animation is function, not decoration. It explains state changes.

## Physics-Based Motion

Use spring animations instead of linear durations. Springs feel natural and are interruptible.

```jsx
// framer-motion spring config
const springConfig = {
  type: "spring",
  stiffness: 300,
  damping: 30
};

// Bouncy spring for playful UI
const bouncySpring = {
  type: "spring",
  stiffness: 400,
  damping: 10
};

// Smooth spring for subtle motion
const smoothSpring = {
  type: "spring",
  stiffness: 200,
  damping: 25
};
```

## Shared Element Transitions

When clicking a card to open details, the image should morph into new position.

```jsx
// framer-motion layoutId
<motion.div layoutId={`card-${id}`}>
  <motion.img layoutId={`image-${id}`} src={image} />
  <motion.h2 layoutId={`title-${id}`}>{title}</motion.h2>
</motion.div>
```

## Scroll-Driven Animation

### Parallax
Background moves slower than foreground:

```jsx
const { scrollY } = useScroll();
const y = useTransform(scrollY, [0, 500], [0, -150]);

<motion.div style={{ y }}>
  {/* Background element */}
</motion.div>
```

### Reveal on Scroll
Elements slide up and fade in as they enter viewport:

```jsx
<motion.div
  initial={{ opacity: 0, y: 50 }}
  whileInView={{ opacity: 1, y: 0 }}
  viewport={{ once: true, margin: "-100px" }}
  transition={{ duration: 0.5 }}
>
```

### Sticky Headers with Transform
Header collapses/transforms on scroll:

```jsx
const { scrollY } = useScroll();
const headerHeight = useTransform(scrollY, [0, 100], [80, 60]);
const titleSize = useTransform(scrollY, [0, 100], [24, 18]);

<motion.header style={{ height: headerHeight }}>
  <motion.h1 style={{ fontSize: titleSize }}>Title</motion.h1>
</motion.header>
```

## Gesture-Driven UI

### Drag-to-Dismiss
Modals and images should be draggable to close:

```jsx
<motion.div
  drag="y"
  dragConstraints={{ top: 0, bottom: 0 }}
  dragElastic={0.2}
  onDragEnd={(_, info) => {
    if (info.offset.y > 100 || info.velocity.y > 500) {
      onClose();
    }
  }}
>
```

### Pull-to-Refresh
Custom implementation with hidden animation layer:

```jsx
const [isPulling, setIsPulling] = useState(false);
const y = useMotionValue(0);

<motion.div
  drag="y"
  dragConstraints={{ top: 0, bottom: 100 }}
  style={{ y }}
  onDrag={(_, info) => setIsPulling(info.offset.y > 50)}
  onDragEnd={async (_, info) => {
    if (info.offset.y > 80) {
      await onRefresh();
    }
  }}
>
  {isPulling && <RefreshIndicator />}
</motion.div>
```

## CSS Transitions (No Library)

For simpler animations, use CSS:

```css
/* Standard transition */
.element {
  transition: all 0.2s ease-out;
}

/* Hover scale */
.card {
  transition: transform 0.2s ease-out, box-shadow 0.2s ease-out;
}
.card:hover {
  transform: translateY(-4px);
  box-shadow: 0 10px 40px rgba(0,0,0,0.15);
}

/* Staggered children (CSS only) */
.list-item {
  animation: fadeInUp 0.4s ease-out backwards;
}
.list-item:nth-child(1) { animation-delay: 0.1s; }
.list-item:nth-child(2) { animation-delay: 0.2s; }
.list-item:nth-child(3) { animation-delay: 0.3s; }

@keyframes fadeInUp {
  from {
    opacity: 0;
    transform: translateY(20px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
```

## Tailwind Animation Classes

```html
<!-- Built-in -->
<div class="animate-pulse">Loading...</div>
<div class="animate-spin">Loading...</div>
<div class="animate-bounce">Scroll down</div>

<!-- Transitions -->
<button class="transition-all duration-200 hover:scale-105 active:scale-95">

<!-- Transform on hover -->
<div class="transition-transform hover:-translate-y-1">
```
