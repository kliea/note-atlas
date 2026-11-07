import fs from "node:fs";
import path from "node:path";
import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";

// Dev-only frame sink for recording walkthroughs: POST a data URL to /__capture?name=0001
// and it is written to data/demo/captures/. Inert unless something posts to it.
function captureSink(): Plugin {
  return {
    name: "atlas-capture-sink",
    apply: "serve",
    configureServer(server) {
      server.middlewares.use("/__capture", (req, res) => {
        const name = (new URL(req.url ?? "", "http://x").searchParams.get("name") ?? "frame").replace(/[^\w.-]/g, "");
        let body = "";
        req.on("data", (c) => (body += c));
        req.on("end", () => {
          const m = body.match(/^data:image\/(png|jpeg);base64,(.+)$/);
          if (!m) { res.statusCode = 400; res.end("bad"); return; }
          const dir = path.resolve(__dirname, "../data/demo/captures");
          fs.mkdirSync(dir, { recursive: true });
          fs.writeFileSync(path.join(dir, `${name}.${m[1] === "png" ? "png" : "jpg"}`), Buffer.from(m[2], "base64"));
          res.end("ok");
        });
      });
    },
  };
}

export default defineConfig({
  plugins: [react(), captureSink()],
  server: {
    port: 5252,
    strictPort: true,
    // Opt-in same-origin API: run with VITE_API_BASE=/api to reach the backend through this
    // dev server (for browsers that only allow one origin, e.g. embedded preview panes).
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8888",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
