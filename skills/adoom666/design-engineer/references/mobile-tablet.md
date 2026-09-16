# Mobile & Tablet Design Reference

Touch design is fundamentally different from mouse interactions.

## Mobile: Thumb Zone & Reachability

### Bottom-Heavy Navigation
Primary actions go in bottom 1/3 of screen. Top corners are dead zones.

```jsx
// Good: Bottom navigation
<nav className="fixed bottom-0 left-0 right-0 h-16 flex items-center justify-around bg-background border-t">
  <NavItem icon={Home} />
  <NavItem icon={Search} />
  <NavItem icon={Plus} primary /> {/* FAB in center */}
  <NavItem icon={Bell} />
  <NavItem icon={User} />
</nav>

// Good: Bottom sheet instead of centered modal
<Sheet>
  <SheetContent side="bottom" className="rounded-t-2xl">
    {/* Content slides up from bottom */}
  </SheetContent>
</Sheet>
```

### Haptic Visuals
Simulate physical press with scale transforms:

```css
.touch-button {
  transition: transform 0.1s ease-out;
}
.touch-button:active {
  transform: scale(0.96);
}
```

```jsx
// Tailwind
<button className="active:scale-95 transition-transform">
```

### Swipe Gestures
Implement swipe-to-delete, swipe-to-archive, swipe-to-go-back.

```jsx
// Using framer-motion
<motion.div
  drag="x"
  dragConstraints={{ left: -100, right: 0 }}
  onDragEnd={(_, info) => {
    if (info.offset.x < -50) onDelete();
  }}
>
```

## Tablet: The Pro Canvas

### Master-Detail Views
Don't stretch lists to full width. Use split-view.

```jsx
// Tablet layout (md breakpoint and up)
<div className="flex h-screen">
  {/* Sidebar - list */}
  <aside className="w-80 border-r overflow-y-auto">
    <ItemList />
  </aside>

  {/* Main - detail */}
  <main className="flex-1 overflow-y-auto">
    <ItemDetail />
  </main>
</div>
```

### Grid Adaptation
Single column on mobile becomes Bento Grid on tablet.

```jsx
<div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
  {/* Cards adapt from list to grid */}
</div>
```

### Navigation Switch
Bottom bar on mobile, vertical rail on tablet.

```jsx
// Responsive navigation
<>
  {/* Mobile: Bottom bar */}
  <nav className="md:hidden fixed bottom-0 left-0 right-0">
    <BottomNav />
  </nav>

  {/* Tablet+: Sidebar rail */}
  <aside className="hidden md:flex fixed left-0 top-0 h-full w-16 flex-col">
    <SideNav />
  </aside>
</>
```

## The Bento Effect

Organize into modular cells instead of endless lists:

```jsx
<div className="grid grid-cols-2 md:grid-cols-4 gap-4">
  {/* Large featured item spans 2 columns */}
  <div className="col-span-2 row-span-2 aspect-square">
    <FeaturedCard />
  </div>

  {/* Regular items */}
  <div className="aspect-square"><Card /></div>
  <div className="aspect-square"><Card /></div>
  <div className="col-span-2"><WideCard /></div>
</div>
```

## Touch Target Sizes

Minimum touch targets: 44x44px (iOS), 48x48dp (Android)

```css
.touch-target {
  min-width: 44px;
  min-height: 44px;
  /* Or use padding to expand hit area */
  padding: 12px;
}
```

```jsx
// Tailwind
<button className="min-w-11 min-h-11 p-3">
```
