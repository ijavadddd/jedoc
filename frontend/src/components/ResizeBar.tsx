interface Props {
  axis: "x" | "y";
  onDelta: (delta: number) => void;
}

export function ResizeBar({ axis, onDelta }: Props) {
  return (
    <div
      role="separator"
      aria-orientation={axis === "x" ? "vertical" : "horizontal"}
      className={
        axis === "x"
          ? "w-1.5 shrink-0 cursor-col-resize bg-line/80 hover:bg-gold/70"
          : "h-1.5 shrink-0 cursor-row-resize bg-line/80 hover:bg-gold/70"
      }
      onPointerDown={(event) => {
        event.preventDefault();
        let last = axis === "x" ? event.clientX : event.clientY;
        const previous = document.body.style.cursor;
        document.body.style.cursor = axis === "x" ? "col-resize" : "row-resize";
        const move = (next: PointerEvent) => {
          const point = axis === "x" ? next.clientX : next.clientY;
          onDelta(point - last);
          last = point;
        };
        const up = () => {
          document.body.style.cursor = previous;
          window.removeEventListener("pointermove", move);
          window.removeEventListener("pointerup", up);
        };
        window.addEventListener("pointermove", move);
        window.addEventListener("pointerup", up);
      }}
    />
  );
}
