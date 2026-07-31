import type { Risk } from '@/api/types';
import { RiskBadge } from '@/components/ui/Badge';
import { riskClass } from '@/lib/format';

/**
 * AI-generated risks.
 *
 * Each item renders its `evidence_metric` — the computed field the model was
 * required to cite. That link back to a deterministic number is what separates
 * a recommendation from a guess, so it's shown rather than hidden.
 */
export function RiskList({ risks }: { risks: Risk[] }) {
  if (risks.length === 0) {
    return <p className="small muted">No risks were identified for this dataset.</p>;
  }

  return (
    <div className="stack" style={{ gap: 12 }}>
      {risks.map((risk) => (
        <article key={risk.id} className={`risk-item ${riskClass(risk.risk_level)}`}>
          <div className="row-between">
            <h3 className="risk-title">{risk.title}</h3>
            <RiskBadge level={risk.risk_level} />
          </div>

          {risk.explanation && <p className="risk-text">{risk.explanation}</p>}

          {risk.affected_items && risk.affected_items.length > 0 && (
            <div className="row" style={{ gap: 6, marginTop: 8 }}>
              {risk.affected_items.map((item) => (
                <span key={item} className="badge badge-neutral">
                  {item}
                </span>
              ))}
            </div>
          )}

          {risk.recommendation && (
            <p className="risk-recommendation">
              <strong>Do this: </strong>
              {risk.recommendation}
            </p>
          )}

          {risk.evidence_metric && (
            <p className="evidence">grounded in {risk.evidence_metric}</p>
          )}
        </article>
      ))}
    </div>
  );
}
