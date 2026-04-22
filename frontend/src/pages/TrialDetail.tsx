import { useParams } from "react-router-dom";

export function TrialDetail() {
  const { trialId } = useParams();
  return (
    <section>
      <h1>Trial Detail</h1>
      <p>
        Placeholder for trial <code>{trialId}</code>. Trial parameters and
        metrics will appear here.
      </p>
    </section>
  );
}
