import { useLocation } from "react-router-dom";

import { NewJob } from "./NewJob";

export function NewJobRoute() {
  const location = useLocation();
  return <NewJob key={location.search} />;
}
