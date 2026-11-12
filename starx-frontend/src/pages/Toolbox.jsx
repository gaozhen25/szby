import { useState } from "react";

import AiImageWorkspace from "../components/toolbox/AiImageWorkspace";
import ProhibitedWordWorkspace from "../components/toolbox/ProhibitedWordWorkspace";
import ScriptRewriteWorkspace from "../components/toolbox/ScriptRewriteWorkspace";
import DigitalHumanWorkspace from "../components/toolbox/DigitalHumanWorkspace";
import PersonReplacementWorkspace from "../components/toolbox/PersonReplacementWorkspace";
import ToolboxNav from "../components/toolbox/ToolboxNav";
import "../styles/toolbox.css";

const prohibited = [
  ["第一", "首选"],
  ["绝对", "确实"],
  ["永久", "长期"],
  ["100%", "高纯度"],
  ["最强大", "显著"],
  ["全网", "平台内"],
];

const initialMessages = [
  { role: "user", text: "帮我生成一张美妆产品的静物摄影图，柔和自然光，高级感" },
  { role: "assistant", text: "好的，生成了一张美妆产品静物图。可以继续提出修改意见。 🧴✨" },
];

export default function Toolbox({ app }) {
  const [tab, setTab] = useState("ai");
  const [message, setMessage] = useState("");
  const [messages, setMessages] = useState(initialMessages);
  const [scriptLink, setScriptLink] = useState("");
  const [rewriteRequest, setRewriteRequest] = useState("");
  const [text, setText] = useState(
    "这是全网第一好用的产品，绝对有效，永久解决你的肌肤问题！100%纯天然成分，效果最强大。"
  );
  const [found, setFound] = useState([]);

  const send = () => {
    if (!message.trim()) return;
    setMessages((current) => [
      ...current,
      { role: "user", text: message.trim() },
      { role: "assistant", text: "已根据你的描述生成新图。如需调整请继续描述。 🖼️✨" },
    ]);
    setMessage("");
  };

  const detectProhibitedWords = () => {
    const result = prohibited.filter(([word]) => text.includes(word));
    setFound(result);
    app.addToast(
      result.length ? `检测到${result.length}个违禁词` : "内容安全",
      result.length ? "warning" : "success"
    );
  };

  const replaceProhibitedWords = () => {
    let next = text;
    found.forEach(([word, replacement]) => {
      next = next.replaceAll(word, replacement);
    });
    setText(next);
    setFound([]);
    app.addToast("已自动修复", "success");
  };

  return (
    <div className="toolbox-shell toolbox-ux-shell">
      <ToolboxNav activeTool={tab} onSelect={setTab} />
      <section className="toolbox-main">
        {tab === "ai" ? (
          <AiImageWorkspace
            app={app}
            message={message}
            messages={messages}
            onMessageChange={setMessage}
            onSend={send}
            onReset={() => setMessages([])}
          />
        ) : null}
        {tab === "person-replacement" ? <PersonReplacementWorkspace app={app} /> : null}
        {tab === "script" ? (
          <ScriptRewriteWorkspace
            app={app}
            videoLink={scriptLink}
            rewriteRequest={rewriteRequest}
            onVideoLinkChange={setScriptLink}
            onRewriteRequestChange={setRewriteRequest}
          />
        ) : null}
        {tab === "check" ? (
          <ProhibitedWordWorkspace
            text={text}
            found={found}
            onTextChange={setText}
            onDetect={detectProhibitedWords}
            onClear={() => {
              setText("");
              setFound([]);
            }}
            onReplaceAll={replaceProhibitedWords}
          />
        ) : null}
        {tab === "digital-human" ? <DigitalHumanWorkspace app={app} /> : null}
      </section>
    </div>
  );
}
