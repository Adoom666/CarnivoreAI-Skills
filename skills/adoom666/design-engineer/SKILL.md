---
name: design-engineer
description: Expert front end design skills which should be used whenever you make any changes to a front-end of a website or application that has a UI (even a console UI). No matter how small of a UI / UX change, this is the skill to always use for any level of front-end development.
---

# Design Engineer

Build software that feels *crafted*, not *assembled*.

## Core Philosophy

**Reject Mediocrity.** Default Bootstrap/Material/unconfigured Tailwind = generic "SaaS look." Fight against defaults.

- **You are an Art Director** - Establish visual language, not just features
- **Think in Systems** - Define rules (spacing, type, color) before building
- **Speed is a Feature** - 60fps animations, instant loads = UX

## Workflow

### 1. Pick an Archetype
Before writing CSS, decide the project's "soul." Pick ONE and commit (CSS patterns for each style).

See [references/archetypes.md](references/archetypes.md) for:
- Swiss/International
- Digital Brutalism
- Soft Pop/Clay
- Glassmorphism
- Dark Future
- Editorial/Luxury

If there is a local project design file (DESIGN.md) or style guide (style-guide.tsx), use those as the primary source of truth for the project's design system.

### 2. Typography (90% of Design)
Never use single-weight Inter for everything.

See [references/typography.md](references/typography.md) for:
- Font pairing strategies (Contrast, Tech, Workhorse)
- Fluid `clamp()` patterns
- Line-height and letter-spacing rules

### 3. Spacing & Layout
Whitespace is active design, not empty space.

See [references/spacing-layout.md](references/spacing-layout.md) for:
- 4px-based spacing scale
- Grid patterns (12-col, Bento, auto-fit)
- Asymmetry and overlap techniques

### 4. Depth & Texture
Flat design is dead.

See [references/depth-texture.md](references/depth-texture.md) for:
- Layered shadow patterns
- Glass/blur effects
- Noise overlays and gradients

### 5. Mobile & Tablet
Touch != mouse.

Always assume you need to design for a completely responsive design and make it look amazing on a mobile platform.

See [references/mobile-tablet.md](references/mobile-tablet.md) for:
- Bottom-heavy navigation (thumb zone)
- Bottom sheets over modals
- Master-detail and Bento patterns
- Touch target sizes (44px minimum)

### 6. Motion & Animation
Animation explains state changes.

See [references/motion.md](references/motion.md) for:
- Spring physics over linear timing
- Shared element transitions
- Scroll-driven animations
- Gesture-driven UI (drag, swipe)

### 7. Tailwind v4 Implementation
See [references/tailwind-v4.md](references/tailwind-v4.md) for:
- @theme configuration patterns
- Component class patterns
- Utility combinations

## Quick Reference

### Shadows (Layered)
```css
box-shadow:
  0 1px 2px rgba(0,0,0,0.07),
  0 4px 8px rgba(0,0,0,0.07),
  0 16px 32px rgba(0,0,0,0.07);
```

### Glass Panel
```css
background: rgba(255,255,255,0.1);
backdrop-filter: blur(20px);
border: 1px solid rgba(255,255,255,0.2);
```

### Fluid Typography
```css
font-size: clamp(2rem, 5vw + 1rem, 4rem);
```

### Spring Animation (framer-motion)
```jsx
transition={{ type: "spring", stiffness: 300, damping: 30 }}
```

### Touch Feedback
```jsx
className="active:scale-95 transition-transform"
```

## Decision Heuristics

| Situation | Default Choice |
|:---|:---|
| Heading + Body font | Contrast pair (Serif + Sans) |
| Dark mode | Dark Future archetype |
| Dashboard | 12-col grid + Bento cells |
| Mobile nav | Bottom bar, not hamburger |
| Modal on mobile | Bottom sheet |
| Card hover | translateY(-4px) + shadow increase |
| Loading state | Skeleton + subtle pulse |
| State change | Spring animation, not linear |

## Validation (REQUIRED)

**NEVER say UI changes are "done" without validating them first.**

### Playwright Validation

After making ANY frontend changes, you MUST:

1. **Run Playwright tests** to verify the UI works:
   ```bash
   npx playwright test <relevant-test-file> --headed
   ```

2. **If no existing test**, write a quick validation script:
   ```bash
   npx playwright test --ui
   ```
   Or create a simple test that:
   - Navigates to the changed page
   - Interacts with the modified component
   - Takes a screenshot for visual verification

3. **Check for console errors** - UI changes should not introduce JS errors

4. **Test interactions**:
   - Clicks, hovers, focus states
   - Dropdowns open/close properly
   - Scrolling works if content overflows
   - Mobile viewport if responsive changes made

### Quick Validation Script Example

```typescript
// Save to e2e/validate-ui-change.spec.ts
import { test, expect } from '@playwright/test';

test('validate UI change', async ({ page }) => {
  await page.goto('/your-page');

  // Interact with the component
  await page.click('[data-testid="your-component"]');

  // Verify it works
  await expect(page.locator('.expected-element')).toBeVisible();

  // Screenshot for visual check
  await page.screenshot({ path: 'validation.png' });
});
```

**DO NOT skip this step. Visual bugs caught in dev save hours of debugging later.**
