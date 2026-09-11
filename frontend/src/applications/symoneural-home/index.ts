/**
 * `symoneural-home` owns the shared shell and the site-wide navigation model.
 *
 * A route imports from here, never from the files underneath: the folder is the unit of
 * ownership, and its public surface is this one file.
 */
export { SymoneuralShell } from "./components/SymoneuralShell";
export { MigrationIndex } from "./components/MigrationIndex";
