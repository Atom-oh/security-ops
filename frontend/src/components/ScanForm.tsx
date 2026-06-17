import { useState } from "react";
import { ScanRequest } from "../api/types";

export interface ScanFormValue {
  req: ScanRequest;
  async: boolean;
}

const labelStyle: React.CSSProperties = { fontSize: "var(--text-xs)", color: "var(--text-secondary)" };
const inputStyle: React.CSSProperties = {
  padding: "var(--space-2) var(--space-3)",
  border: "1px solid var(--border-default)",
  borderRadius: "var(--radius-md)",
  background: "var(--surface-card)",
};

async function fileToB64(file: File): Promise<string> {
  const buf = await file.arrayBuffer();
  let bin = "";
  const bytes = new Uint8Array(buf);
  for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
  return btoa(bin);
}

// Only source code is uploaded (js, ts, py, java, cpp, c, go families) — everything else
// (assets, docs, lockfiles, binaries) is filtered out client-side.
const CODE_EXTENSIONS = new Set([
  ".js", ".jsx", ".mjs", ".cjs",
  ".ts", ".tsx",
  ".py",
  ".java",
  ".cpp", ".cc", ".cxx", ".hpp", ".hh",
  ".c", ".h",
  ".go",
]);

function isCodeFile(name: string): boolean {
  const dot = name.lastIndexOf(".");
  if (dot < 0) return false;
  return CODE_EXTENSIONS.has(name.slice(dot).toLowerCase());
}

export function ScanForm({ busy, onSubmit }: { busy: boolean; onSubmit: (v: ScanFormValue) => void }) {
  const [source, setSource] = useState<"container" | "upload">("container");
  const [projectPath, setProjectPath] = useState("/app/sample-target");
  const [maxFiles, setMaxFiles] = useState(3);
  const [passAtK, setPassAtK] = useState(1);
  const [sandbox, setSandbox] = useState(false);
  const [async, setAsync] = useState(false);
  const [files, setFiles] = useState<{ path: string; content_b64: string }[]>([]);

  async function onFiles(list: FileList | null) {
    if (!list) return;
    const code = Array.from(list).filter((f) =>
      isCodeFile((f as any).webkitRelativePath || f.name),
    );
    const out: { path: string; content_b64: string }[] = [];
    for (const f of code.slice(0, 50)) {
      out.push({ path: (f as any).webkitRelativePath || f.name, content_b64: await fileToB64(f) });
    }
    setFiles(out);
  }

  function submit() {
    const req: ScanRequest = { max_files: maxFiles, pass_at_k: passAtK, sandbox_enabled: sandbox };
    if (source === "container") req.project_path = projectPath;
    else req.upload = { files };
    onSubmit({ req, async });
  }

  return (
    <div className="card" style={{ padding: "var(--space-6)", display: "grid", gap: "var(--space-5)" }}>
      <h2 style={{ fontSize: "var(--text-lg)" }}>스캔 설정</h2>

      <div style={{ display: "flex", gap: "var(--space-4)" }}>
        {(["container", "upload"] as const).map((s) => (
          <label key={s} style={{ display: "flex", gap: "var(--space-2)", alignItems: "center" }}>
            <input type="radio" checked={source === s} onChange={() => setSource(s)} />
            {s === "container" ? "컨테이너 경로" : "로컬 폴더 업로드"}
          </label>
        ))}
      </div>

      {source === "container" ? (
        <label style={{ display: "grid", gap: "var(--space-1)" }}>
          <span style={labelStyle}>대상 프로젝트 경로 (AgentCore 컨테이너 내부)</span>
          <input style={inputStyle} value={projectPath} onChange={(e) => setProjectPath(e.target.value)} />
        </label>
      ) : (
        <label style={{ display: "grid", gap: "var(--space-1)" }}>
          <span style={labelStyle}>폴더 선택 (최대 50파일)</span>
          {/* @ts-expect-error webkitdirectory is non-standard */}
          <input type="file" webkitdirectory="" multiple onChange={(e) => onFiles(e.target.files)} />
          <span style={{ fontSize: "var(--text-xs)", color: "var(--text-muted)" }}>{files.length}개 선택됨</span>
        </label>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "var(--space-4)" }}>
        <label style={{ display: "grid", gap: "var(--space-1)" }}>
          <span style={labelStyle}>최대 파일 수 (비용 제어)</span>
          <input
            style={inputStyle}
            type="number"
            min={1}
            max={50}
            value={maxFiles}
            onChange={(e) => setMaxFiles(Number(e.target.value))}
          />
        </label>
        <label style={{ display: "grid", gap: "var(--space-1)" }}>
          <span style={labelStyle}>Hunter 독립 실행 (pass@k)</span>
          <select style={inputStyle} value={passAtK} onChange={(e) => setPassAtK(Number(e.target.value))}>
            <option value={1}>1회 (빠름)</option>
            <option value={3}>3회 (정밀)</option>
            <option value={5}>5회 (최고 정밀)</option>
          </select>
        </label>
      </div>

      <label style={{ display: "flex", gap: "var(--space-2)", alignItems: "center" }}>
        <input type="checkbox" checked={sandbox} onChange={(e) => setSandbox(e.target.checked)} />
        <span>샌드박스 PoC 검증 (Code Interpreter)</span>
      </label>

      <div style={{ display: "flex", gap: "var(--space-4)" }}>
        {[
          { v: false, label: "동기 (권장 · 결과까지 대기)" },
          { v: true, label: "비동기 (실험적)" },
        ].map((m) => (
          <label key={String(m.v)} style={{ display: "flex", gap: "var(--space-2)", alignItems: "center" }}>
            <input type="radio" checked={async === m.v} onChange={() => setAsync(m.v)} />
            {m.label}
          </label>
        ))}
      </div>

      <div>
        <button className="btn-primary" disabled={busy} onClick={submit}>
          {busy ? "스캔 중… (수 분 소요)" : "스캔 시작"}
        </button>
        <div style={{ fontSize: "var(--text-xs)", color: "var(--text-muted)", marginTop: "var(--space-2)" }}>
          파일당 약 30~60초 (Opus 다중 에이전트). 동기 모드는 완료까지 기다립니다 — 파일 수가 많으면 수 분 걸릴 수 있습니다.
        </div>
      </div>
    </div>
  );
}
