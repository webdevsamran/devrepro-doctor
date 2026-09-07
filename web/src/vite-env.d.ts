/// <reference types="vite/client" />

// Pulls in Vite's ambient module declarations, including `declare module
// '*.css' {}`. TypeScript 6 reports TS2882 for a side-effect import with no
// type declaration, so `import './styles.css'` in main.tsx fails to compile
// without this. TypeScript 5 accepted it silently.
