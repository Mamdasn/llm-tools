// Local Codex integration for Context Mode 1.0.169.
// Install this overlay inside the upstream package; keep its runtime separate.
import { delimiter, dirname } from 'node:path';

process.env.PATH = [
  dirname(process.execPath),
  process.env.CODEX_BIN_DIR,
  process.env.PATH,
].filter(Boolean).join(delimiter);
process.env.CONTEXT_MODE_PLATFORM = 'codex';

const mode = process.argv[2];
if (mode === 'server') {
  process.env.CONTEXT_MODE_PROJECT_DIR ||= process.cwd();
  await import('../server.bundle.mjs');
} else if (['pretooluse', 'posttooluse', 'sessionstart', 'precompact', 'userpromptsubmit', 'stop'].includes(mode)) {
  await import(new URL(`../hooks/codex/${mode}.mjs`, import.meta.url));
} else {
  throw new Error(`Unsupported Context Mode entrypoint: ${mode}`);
}
