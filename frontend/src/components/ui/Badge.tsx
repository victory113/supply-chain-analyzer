import type { ReactNode } from 'react';

import type { RiskLevel } from '@/api/types';

type Tone = 'high' | 'medium' | 'low' | 'neutral' | 'accent';

interface BadgeProps {
  tone?: Tone;
  children: ReactNode;
}

export function Badge({ tone = 'neutral', children }: BadgeProps) {
  return <span className={`badge badge-${tone}`}>{children}</span>;
}

export function RiskBadge({ level }: { level: RiskLevel | null | undefined }) {
  if (!level) return <Badge tone="neutral">Unknown</Badge>;
  return <Badge tone={level.toLowerCase() as Tone}>{level}</Badge>;
}
