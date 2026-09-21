import { useEffect, useState } from "react";
import { CanvasBoard } from "./CanvasBoard";

const API = "http://127.0.0.1:8889";

export default function App() {
  const [backend, setBackend] = useState("loading");

  useEffect(() => {
    void fetch(`${API}/health`)
      .then((r) => r.json())
      .then((data: { status?: string }) => {
        setBackend(data.status === "ok" ? "ok" : "error");
      })
      .catch(() => setBackend("error"));
  }, []);

  return (
    <div className="app">
      <header>
        <strong>SCA experiment</strong>
        <span>backend = {backend}</span>
      </header>
      <CanvasBoard />
    </div>
  );
}
