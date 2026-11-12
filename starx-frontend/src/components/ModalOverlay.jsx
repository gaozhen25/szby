import { createPortal } from "react-dom";

/**
 * Full-viewport modal shell mounted on document.body so page chrome
 * (sidebar / topbar stacking) cannot sit above the overlay or receive clicks.
 * Backdrop clicks are intentionally not closed here — parents control dismiss.
 */
export default function ModalOverlay({
  className = "",
  children,
  portal = true,
  ...props
}) {
  const node = (
    <div
      className={["modal-overlay", className].filter(Boolean).join(" ")}
      {...props}
    >
      {children}
    </div>
  );

  if (!portal || typeof document === "undefined") return node;
  return createPortal(node, document.body);
}
