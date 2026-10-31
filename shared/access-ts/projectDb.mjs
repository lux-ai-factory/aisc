// A project's database: its name, and its address from an app's template. Plain JavaScript, so the
// apps' scripts (node, no TypeScript loader) and their TypeScript code read the same file.
//
// The twin of aisc_identity.projectdb (shared/identity); both run projectdb-cases.json. Only a pid in
// its canonical form (any case, nothing around it) names a database: `project_` and its 32 lowercase
// hex digits. A template is a URL with `{database}` as its path, its credentials percent-encoded;
// projectDsn() drops only Prisma's own options and keeps every libpq option.

export const PLACEHOLDER = "{database}";
export const PRISMA_OPTIONS = new Set(["schema", "connection_limit", "pool_timeout"]);
export const MAINTENANCE_DATABASE = "postgres";

const PID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const NAME = /^project_([0-9a-f]{32})$/;
const DATABASE = /^[a-z_][a-z0-9_]*$/;
const URL_PARTS =
  /^(postgres(?:ql)?)(?:\+[a-z0-9]+)?:\/\/(?:([^@/?#]*)@)?([^/?#]*)\/([^?#]*)(?:\?([^#]*))?$/;

export class NotAPid extends Error {}

export function databaseName(pid) {
  if (typeof pid !== "string" || !PID.test(pid)) throw new NotAPid(`not a project id: ${JSON.stringify(pid)}`);
  return `project_${pid.toLowerCase().replace(/-/g, "")}`;
}

export function pidOf(name) {
  const found = NAME.exec(typeof name === "string" ? name : "");
  if (!found) return null;
  const h = found[1];
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
}

export function projectDsn(template, database, { driver = null } = {}) {
  const found = URL_PARTS.exec(typeof template === "string" ? template : "");
  if (!found || found[4] !== PLACEHOLDER)
    throw new Error(`a database template is a postgresql:// URL whose path is ${PLACEHOLDER}`);
  if (typeof database !== "string" || !DATABASE.test(database))
    throw new Error(`not a database name: ${JSON.stringify(database)}`);
  const [, , userinfo, host, , query] = found;
  const scheme = driver ? `postgresql+${driver}` : "postgresql";
  const credentials = userinfo === undefined ? "" : splitOnce(userinfo, ":").map(quoted).join(":") + "@";
  const options = (query ?? "")
    .split("&")
    .filter((part) => part && !PRISMA_OPTIONS.has(decoded(part.split("=")[0])));
  return `${scheme}://${credentials}${host}/${database}${options.length ? "?" + options.join("&") : ""}`;
}

export function maintenanceDsn(template, { driver = null } = {}) {
  return projectDsn(template, MAINTENANCE_DATABASE, { driver });
}

function splitOnce(text, separator) {
  const at = text.indexOf(separator);
  return at < 0 ? [text] : [text.slice(0, at), text.slice(at + 1)];
}

function decoded(part) {
  return decodeURIComponent(part.replace(/%(?![0-9A-Fa-f]{2})/g, "%25"));
}

/** A user name or password percent-encoded once: an encoded one stays as it is, a raw `{` or `%` is encoded. */
function quoted(part) {
  return encodeURIComponent(decoded(part));
}
