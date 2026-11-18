"use client";

import { useEffect, useState } from "react";
import { Input } from "./ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select";

interface Props {
  models: string[];
  value: string;
  onChange: (model: string) => void;
}

export function ModelSelect({ models, value, onChange }: Props) {
  const [custom, setCustom] = useState(false);
  const listed = value !== "" && models.includes(value);
  const showCustom = custom || (value !== "" && !listed);

  useEffect(() => {
    if (value && !models.includes(value)) setCustom(true);
  }, [models, value]);

  return (
    <div className="space-y-1">
      <Select
        value={showCustom ? "custom" : value || "default"}
        onValueChange={(next) => {
          if (next === "custom") {
            setCustom(true);
            if (models.includes(value)) onChange("");
            return;
          }
          setCustom(false);
          onChange(next === "default" ? "" : next);
        }}
      >
        <SelectTrigger className="h-8 font-mono text-[11px]">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="default">Account default</SelectItem>
          {models.map((model) => (
            <SelectItem key={model} value={model}>
              {model}
            </SelectItem>
          ))}
          <SelectItem value="custom">Custom id…</SelectItem>
        </SelectContent>
      </Select>
      {showCustom && <Input className="h-8 font-mono text-[11px]" placeholder="model id" value={value} onChange={(event) => onChange(event.target.value)} />}
    </div>
  );
}
