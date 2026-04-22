import { useParams } from "react-router-dom";

export function JobDetail() {
  const { jobId } = useParams();
  return (
    <section>
      <h1>Job Detail</h1>
      <p>
        Placeholder for job <code>{jobId}</code>. Metrics, charts, and report
        content will appear here.
      </p>
    </section>
  );
}
