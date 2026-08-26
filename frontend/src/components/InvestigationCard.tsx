import type { AiEvidence, AiInvestigation } from "../api/types";

interface Props {
  investigation: AiInvestigation;
}

function evidenceMeta(item: AiEvidence): string {
  const parts: string[] = [];
  if (item.work_date) parts.push(item.work_date);
  if (item.domains.length > 0) parts.push(item.domains.join(" → "));
  if (item.task_title) parts.push(item.task_title);
  return parts.join(" · ");
}

export default function InvestigationCard({ investigation }: Props) {
  return (
    <article className="investigation-card" aria-label="AI investigation result">
      <div className="investigation-section investigation-finding">
        <span className="investigation-label">Finding</span>
        <h3>{investigation.title}</h3>
        <p>{investigation.finding}</p>
      </div>

      {investigation.evidence.length > 0 ? (
        <div className="investigation-section">
          <span className="investigation-label">Evidence</span>
          <div className="investigation-evidence-list">
            {investigation.evidence.map((item) => (
              <div className="investigation-evidence" key={item.id}>
                <strong>{item.label}</strong>
                {evidenceMeta(item) ? <span>{evidenceMeta(item)}</span> : null}
                <p>{item.detail}</p>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {investigation.impact ? (
        <div className="investigation-section">
          <span className="investigation-label">Impact</span>
          <p>{investigation.impact}</p>
        </div>
      ) : null}

      {investigation.suggested_action ? (
        <div className="investigation-section investigation-action">
          <span className="investigation-label">Suggested review</span>
          <p>{investigation.suggested_action}</p>
        </div>
      ) : null}
    </article>
  );
}
