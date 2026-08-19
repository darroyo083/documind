import { createElement, useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";

type RevealTag = "article" | "div" | "header" | "main" | "section";

export default function ScrollReveal({
  as = "div",
  children,
  className = "",
  delay = 0,
  ...attributes
}: {
  as?: RevealTag;
  children: ReactNode;
  className?: string;
  delay?: number;
  "aria-label"?: string;
  "aria-labelledby"?: string;
}) {
  const elementRef = useRef<HTMLElement | null>(null);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const element = elementRef.current;
    if (!element) return;

    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reducedMotion || !("IntersectionObserver" in window)) {
      setVisible(true);
      return;
    }

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (!entry.isIntersecting) return;
        setVisible(true);
        observer.unobserve(element);
      },
      { rootMargin: "0px 0px -10% 0px", threshold: 0.14 },
    );

    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  const style = { "--dm-reveal-delay": `${delay}ms` } as CSSProperties;
  return createElement(
    as,
    {
      ...attributes,
      ref: elementRef,
      className: `dm-reveal ${visible ? "dm-reveal-visible" : ""} ${className}`.trim(),
      style,
    },
    children,
  );
}
