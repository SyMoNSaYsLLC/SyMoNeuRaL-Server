import { MigrationIndex, SymoneuralShell } from "@/applications/symoneural-home";

/** Thin by design: the route owns the URL, the application owns the behaviour. */
export default function HomePage() {
  return (
    <SymoneuralShell eyebrow="Canonical frontend" title="SyMoNeuRaL">
      <MigrationIndex />
    </SymoneuralShell>
  );
}
