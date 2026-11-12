import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import test from "node:test";

const readOptional = (url) => (existsSync(url) ? readFileSync(url, "utf8") : "");

const accountSource = readFileSync(new URL("./AccountProfile.jsx", import.meta.url), "utf8");
const modalSource = readFileSync(
  new URL("../components/KnowledgeBaseModal.jsx", import.meta.url),
  "utf8"
);
const managerSource = readOptional(
  new URL("../components/knowledge-base/KnowledgeBaseManager.jsx", import.meta.url)
);
const editorSource = readOptional(
  new URL("../components/knowledge-base/KnowledgeBaseEditor.jsx", import.meta.url)
);
const accountStyles = readOptional(new URL("../styles/account-profile.css", import.meta.url));
const knowledgeStyles = readOptional(new URL("../styles/knowledge-base.css", import.meta.url));

test("account profile follows Kim hierarchy while keeping develop paging and search", () => {
  assert.match(accountSource, /import "\.\.\/styles\/account-profile\.css"/);
  assert.match(accountSource, /className="account-profile-ux-shell"/);
  assert.match(accountSource, /account-profile-ux-header/);
  assert.match(accountSource, /accountPlatforms = \[[\s\S]*icon:/);
  assert.match(accountSource, /platformIcons/);
  assert.match(accountSource, /account-platform-filter/);
  assert.match(accountSource, /account-hero-actions-right/);
  assert.match(accountSource, /account-pagination/);
  assert.match(accountSource, /pageSize: 4/);
  assert.match(accountSource, /app\.loadAccountsPage/);
  assert.match(accountSource, /accountKeyword/);
  assert.doesNotMatch(accountSource, /Array\.from\(\{ length: accountTotalPages/);
});

test("every account card keeps real switch edit and confirmed delete actions", () => {
  assert.match(accountSource, /app\.switchAccount\(account\.id\)/);
  assert.match(accountSource, /app\.openAccountModal\?\.\(account\)/);
  assert.match(accountSource, /confirmDelete\(account\)/);
  assert.match(accountSource, /window\.confirm/);
  assert.doesNotMatch(accountSource, /future: dropdown menu/);
  assert.doesNotMatch(accountSource, /className="btn-more-menu"/);
});

test("knowledge summary describes real knowledge bases instead of calling them accounts", () => {
  assert.match(accountSource, /可用知识库/);
  assert.match(accountSource, /已载入图片素材/);
  assert.match(accountSource, /app\.knowledgeBasePage\?\.total\s*\?\?\s*knowledgeBases\.length/);
  assert.doesNotMatch(accountSource, /已关联 \{boundKBCount\} 个账号/);
  assert.match(accountSource, /app\.openKnowledgeBaseModal\(\)/);
});

test("knowledge modal opens on Kim manager and owns keyboard focus", () => {
  assert.match(modalSource, /import KnowledgeBaseManager/);
  assert.match(modalSource, /import KnowledgeBaseEditor/);
  assert.match(modalSource, /editingKnowledgeBase\?\.id \? "editor" : "manager"/);
  assert.match(modalSource, /role="dialog"/);
  assert.match(modalSource, /aria-modal="true"/);
  assert.match(modalSource, /event\.key !== "Tab"/);
  assert.match(modalSource, /querySelectorAll/);
  assert.match(modalSource, /!dialogRef\.current\?\.contains\(document\.activeElement\)/);
  assert.match(modalSource, /previouslyFocused/);
  assert.match(modalSource, /previouslyFocused\.focus\(\)/);
});

test("Kim knowledge manager uses develop list search pagination edit and delete", () => {
  assert.match(managerSource, /品牌知识库/);
  assert.match(managerSource, /knowledgeBaseList/);
  assert.match(managerSource, /knowledgeBasePage/);
  assert.match(managerSource, /knowledgeBase\.industry \|\| "品牌资料"/);
  assert.match(managerSource, /app\.loadKnowledgeBasesPage/);
  assert.match(managerSource, /app\.openKnowledgeBaseModal\(knowledgeBase\)/);
  assert.match(managerSource, /window\.confirm/);
  assert.match(managerSource, /app\.deleteKnowledgeBase\(knowledgeBase\)/);
  assert.match(managerSource, /\+ 新建知识库/);
  assert.match(managerSource, /上一页/);
  assert.match(managerSource, /下一页/);
});

test("knowledge editor keeps real fields and locks writes without fake controls", () => {
  assert.match(editorSource, /normalizeKnowledgeBasePayload/);
  assert.match(editorSource, /KNOWLEDGE_BASE_FIELD_OPTIONS/);
  assert.match(editorSource, /所属行业/);
  assert.match(editorSource, /form\.industry/);
  assert.match(editorSource, /app\.createKnowledgeBase\(payload\)/);
  assert.match(editorSource, /app\.updateKnowledgeBase\(app\.editingKnowledgeBase\.id, payload\)/);
  assert.match(editorSource, /const \[isSaving, setIsSaving\] = useState\(false\)/);
  assert.match(editorSource, /if \(isSaving \|\| isUploading\) return/);
  assert.doesNotMatch(editorSource, /已保存草稿/);
  assert.doesNotMatch(editorSource, /onClick=\{\(\) => \{\}\}/);
});

test("knowledge editor uploads local image materials and stores returned OSS urls", () => {
  assert.match(editorSource, /type="file"/);
  assert.match(editorSource, /accept="image\/jpeg,image\/png,image\/webp"/);
  assert.match(editorSource, /multiple/);
  assert.match(editorSource, /app\.uploadKnowledgeBaseImages\(files\)/);
  assert.match(editorSource, /uploaded\.map\(\(item\) => item\.url\)/);
  assert.match(editorSource, /knowledge-material-card/);
  assert.doesNotMatch(editorSource, /图片素材链接 \$\{index \+ 1\}/);
});

test("knowledge image upload unlocks after completion and supports double-click preview", () => {
  assert.match(editorSource, /mountedRef\.current = true/);
  assert.match(editorSource, /if \(mountedRef\.current\) setIsUploading\(false\)/);
  assert.match(editorSource, /import MediaLightbox, \{ useMediaLightbox \}/);
  assert.match(editorSource, /onDoubleClick=\{\(\) => previewImageMaterial\(index\)\}/);
  assert.match(editorSource, /mediaLightbox\.openMedia\(slides, index\)/);
  assert.match(editorSource, /<MediaLightbox/);
});

test("account and knowledge styles isolate Kim visuals from the excluded report", () => {
  assert.match(accountStyles, /\.account-profile-ux-shell \.account-platform-filter/);
  assert.match(accountStyles, /\.account-profile-ux-shell \.account-hero-card/);
  assert.match(accountStyles, /\.account-profile-ux-shell \.account-grid/);
  assert.match(accountStyles, /grid-template-columns:\s*repeat\(4,\s*minmax\(0,\s*1fr\)\)/);
  assert.match(accountStyles, /@media\s*\(max-width:\s*1100px\)/);
  assert.match(knowledgeStyles, /\.knowledge-modal-ux \.knowledge-library-modal/);
  assert.match(knowledgeStyles, /\.knowledge-modal-ux \.knowledge-library-item/);
  assert.match(knowledgeStyles, /@media\s*\(max-width:\s*700px\)/);
  assert.match(knowledgeStyles, /@media\s*\(prefers-reduced-motion:\s*reduce\)[\s\S]*\.knowledge-modal-ux \.knowledge-library-spinner[\s\S]*animation:\s*none/);
  assert.doesNotMatch(`${accountStyles}\n${knowledgeStyles}`, /\.report-|account-report/);
});
