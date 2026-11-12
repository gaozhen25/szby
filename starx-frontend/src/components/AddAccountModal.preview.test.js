import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const modalSource = readFileSync(new URL("./AddAccountModal.jsx", import.meta.url), "utf8");
const appHookSource = readFileSync(new URL("../hooks/useStarxApp.js", import.meta.url), "utf8");

test("account modal marks every required field and shows all missing-field messages", () => {
  assert.match(modalSource, /<label>平台 <span[^>]*>\*<\/span><\/label>/);
  assert.match(modalSource, /app\.addToast\(errors\.join\("；"\), "warning"\)/);
  assert.match(modalSource, /validateAccountProfileStep\(form, step\)/);
});

test("advanced optional profile fields live on platform step instead of basics step", () => {
  const step1 = modalSource.match(/\{step === 1 && \([\s\S]*?\{step === 2 && \(/)?.[0] || "";
  const step2 = modalSource.match(/\{step === 2 && \([\s\S]*?\{step === 3 && \(/)?.[0] || "";
  assert.doesNotMatch(step1, /高级信息（可选）/);
  assert.match(step2, /高级信息（可选） 行业、受众、城市等可稍后填写/);
  assert.match(step2, /showAdvancedInfo/);
  assert.match(step2, /label>行业<\/label>/);
  assert.match(step2, /label>目标人群<\/label>/);
});

test("Douyin and Xiaohongshu use platform handles instead of homepage links", () => {
  assert.match(modalSource, /配置自己的\{platform\}号/);
  assert.match(modalSource, /form\.platformAccounts/);
  assert.match(modalSource, /请输入抖音号/);
  assert.match(modalSource, /请输入小红书号/);
  assert.match(modalSource, /对标博主账号/);
  assert.match(modalSource, /（选填）/);
  assert.doesNotMatch(
    modalSource,
    /对标博主账号\{\s*" "\s*\}\s*<span style=\{\{ color: "var\(--color-accent-red\)" \}\}>\*<\/span>/,
  );
});

test("updating the current account invalidates and reloads its dashboard", () => {
  const updateAccountSource = appHookSource.match(
    /const updateAccount = useCallback\([\s\S]*?\n  const deleteAccount = useCallback/,
  )?.[0] || "";
  assert.match(updateAccountSource, /setDashboard\(null\)/);
  assert.match(updateAccountSource, /starxApi\.getDashboard\(account\.id\)/);
  assert.match(updateAccountSource, /currentAccountIdRef\.current === account\.id/);
  assert.match(updateAccountSource, /setDashboard\(dashboardData\)/);
});

test("account modal has a top-right close button that requires confirmation", () => {
  assert.match(modalSource, /className="account-modal-close"/);
  assert.match(modalSource, /aria-label="关闭"/);
  assert.match(modalSource, /const requestClose = \(\) => \{/);
  assert.match(modalSource, /window\.confirm/);
  assert.match(modalSource, /requestClose\(\)/);
});

test("quick knowledge base creation selects the newly created knowledge base", () => {
  assert.match(modalSource, /openKnowledgeBaseModal\(null,\s*\{/);
  assert.match(modalSource, /onCreated:\s*\(knowledgeBase\)/);
  assert.match(modalSource, /knowledgeBaseId:\s*knowledgeBase\.id/);
  assert.match(appHookSource, /knowledgeBaseCreatedCallbackRef/);
  assert.match(appHookSource, /onCreated\?\.\(knowledgeBase\)/);
});
