"use client";

import dynamic from "next/dynamic";

const Workstation = dynamic(() => import("@/App").then((mod) => mod.App), {
  ssr: false,
  loading: () => <div className="grid h-screen place-items-center text-sm text-muted-foreground">Opening Jedoc…</div>,
});

export default function Page() {
  return <Workstation />;
}
