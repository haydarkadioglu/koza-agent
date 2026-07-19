import { type ComponentProps } from "solid-js"

export const Mark = (props: { class?: string }) => {
  return (
    <svg
      data-component="logo-mark"
      classList={{ [props.class ?? ""]: !!props.class }}
      viewBox="0 0 24 24"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
    >
      <path d="M12 2 C7 6, 7 18, 12 22 C17 18, 17 6, 12 2 Z" stroke="var(--icon-strong-base)" stroke-width="2" stroke-linejoin="round" fill="none"/>
      <path d="M12 6 C9.5 9, 9.5 15, 12 18 C14.5 15, 14.5 9, 12 6 Z" fill="var(--icon-weak-base)"/>
      <circle cx="12" cy="12" r="1.5" fill="var(--icon-strong-base)"/>
    </svg>
  )
}

export const Splash = (props: Pick<ComponentProps<"svg">, "ref" | "class">) => {
  return (
    <svg
      ref={props.ref}
      data-component="logo-splash"
      classList={{ [props.class ?? ""]: !!props.class }}
      viewBox="0 0 100 100"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
    >
      <path d="M50 10 C30 25, 30 75, 50 90 C70 75, 70 25, 50 10 Z" stroke="var(--icon-strong-base)" stroke-width="6" stroke-linejoin="round" fill="none"/>
      <path d="M50 26 C38 38, 38 62, 50 74 C62 62, 62 38, 50 26 Z" fill="var(--icon-base)"/>
      <circle cx="50" cy="50" r="6" fill="var(--v2-background-bg-base, #1e1e24)"/>
    </svg>
  )
}

export const Logo = (props: { class?: string }) => {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 160 40"
      fill="none"
      classList={{ [props.class ?? ""]: !!props.class }}
    >
      {/* Cocoon Mark on the left */}
      <g transform="translate(5, 5) scale(1.4)">
        <path d="M12 2 C7 6, 7 18, 12 22 C17 18, 17 6, 12 2 Z" stroke="var(--icon-strong-base)" stroke-width="2" stroke-linejoin="round" fill="none"/>
        <path d="M12 6 C9.5 9, 9.5 15, 12 18 C14.5 15, 14.5 9, 12 6 Z" fill="var(--icon-weak-base)"/>
        <circle cx="12" cy="12" r="1.5" fill="var(--icon-strong-base)"/>
      </g>
      {/* KOZA Text in modern futuristic styling */}
      <text 
        x="48" 
        y="27" 
        fill="var(--v2-text-text-base, currentColor)" 
        font-family="system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif" 
        font-weight="800" 
        font-size="22" 
        letter-spacing="2"
      >
        KOZA
      </text>
    </svg>
  )
}
