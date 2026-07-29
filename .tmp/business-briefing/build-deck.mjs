import fs from "node:fs/promises";
import { Presentation, PresentationFile } from "@oai/artifact-tool";

const OUTPUT = "/Users/birdy/NyquisteProjects/weixin-blog-publish/docs/weixin-blog-secretariat-business-briefing-v3.pptx";
const PREVIEW_DIR = "/Users/birdy/NyquisteProjects/weixin-blog-publish/.tmp/business-briefing/rendered";
const ARCHITECTURE_PNG = "/Users/birdy/NyquisteProjects/weixin-blog-publish/.tmp/business-briefing/business-architecture.png";

const W = 1280;
const H = 720;
const C = {
  white: "#FFFFFF",
  ink: "#0A0A0A",
  muted: "#62666D",
  panel: "#EDEDED",
  rule: "#B8BCC4",
  accent: "#6DCBF4",
  blue: "#3D8DFF",
  paleBlue: "#EAF6FC",
  orange: "#F6A84A",
  paleOrange: "#FFF4E8",
  purple: "#8B5CF6",
  palePurple: "#F2EDFF",
  pink: "#D9468F",
  palePink: "#FCECF5",
  green: "#218C6B",
  paleGreen: "#EAF7F2",
  red: "#C63D3D",
  paleRed: "#FBECEC",
};
const FONT = "Arial";

function addText(slide, name, text, x, y, w, h, size, options = {}) {
  const shape = slide.shapes.add({
    geometry: "textbox",
    name,
    position: { left: x, top: y, width: w, height: h },
    fill: "none",
    line: { style: "solid", fill: "none", width: 0 },
  });
  shape.text = text;
  shape.text.style = {
    fontSize: size,
    typeface: FONT,
    color: options.color ?? C.ink,
    bold: options.bold ?? false,
    alignment: options.align ?? "left",
    verticalAlignment: options.valign ?? "top",
    autoFit: options.autoFit ?? "shrinkText",
  };
  return shape;
}

function addBox(slide, name, x, y, w, h, fill, stroke = "none", radius = 14) {
  return slide.shapes.add({
    geometry: "roundRect",
    name,
    position: { left: x, top: y, width: w, height: h },
    fill,
    line: { style: "solid", fill: stroke, width: stroke === "none" ? 0 : 1.2 },
    borderRadius: radius,
  });
}

function addLine(slide, name, x, y, w, h, color = C.rule, width = 1, dashed = false) {
  return slide.shapes.add({
    geometry: "line",
    name,
    position: { left: x, top: y, width: w, height: h },
    fill: "none",
    line: { style: dashed ? "dashed" : "solid", fill: color, width },
  });
}

function addArrow(slide, name, x, y, w, h, fill = C.blue) {
  return slide.shapes.add({
    geometry: "rightArrow",
    name,
    position: { left: x, top: y, width: w, height: h },
    fill,
    line: { style: "solid", fill, width: 0 },
  });
}

function addLeftArrow(slide, name, x, y, w, h, fill = C.blue) {
  return slide.shapes.add({
    geometry: "leftArrow",
    name,
    position: { left: x, top: y, width: w, height: h },
    fill,
    line: { style: "solid", fill, width: 0 },
  });
}

function addSlideHeader(slide, title, number, kicker = "微信内容发布秘书处") {
  addText(slide, `slide-${number}-kicker`, kicker, 42, 30, 380, 24, 15, {
    color: C.muted,
    bold: true,
  });
  addText(slide, `slide-${number}-title`, title, 42, 62, 1160, 82, 38, {
    bold: true,
  });
  addText(slide, `slide-${number}-number`, String(number).padStart(2, "0"), 1180, 662, 58, 22, 12, {
    color: C.muted,
    align: "right",
  });
}

function setNotes(slide, sources, presenter = "") {
  const sourceLines = sources.map((s) => `- ${s}`).join("\n");
  const notes = `${presenter ? `${presenter}\n\n` : ""}[Sources]\n${sourceLines}\n[/Sources]`;
  slide.speakerNotes.textFrame.setText(notes);
  slide.speakerNotes.setVisible(true);
}

function addFlatPoint(slide, index, title, body, x, y, w, accent = C.blue) {
  addText(slide, `point-${index}-num`, String(index).padStart(2, "0"), x, y, 55, 34, 18, {
    color: accent,
    bold: true,
  });
  addLine(slide, `point-${index}-rule`, x, y + 38, w, 0, C.rule, 1);
  addText(slide, `point-${index}-title`, title, x, y + 56, w, 44, 25, { bold: true });
  addText(slide, `point-${index}-body`, body, x, y + 108, w, 92, 18, { color: C.muted });
}

async function main() {
  await fs.mkdir(PREVIEW_DIR, { recursive: true });
  const architecturePng = await fs.readFile(ARCHITECTURE_PNG);
  const deck = Presentation.create({ slideSize: { width: W, height: H } });

  // Slide 1 — sparse Codex Grid cover.
  {
    const slide = deck.slides.add();
    slide.background.fill = C.white;
    addText(slide, "cover-kicker", "NYQUISTE AI 全球全家桶 · 组织运营", 42, 40, 650, 42, 22, {
      bold: true,
      color: C.blue,
    });
    addText(slide, "cover-title", "微信内容发布秘书处", 42, 205, 950, 150, 66, {
      bold: true,
      valign: "bottom",
    });
    addText(
      slide,
      "cover-subtitle",
      "把投稿贡献转化为可追踪、可控制的组织内容与用户资格依据",
      42,
      430,
      760,
      105,
      28,
      { color: C.muted },
    );
    addBox(slide, "cover-accent-block", 1055, 84, 160, 160, C.accent, "none", 0);
    addText(slide, "cover-date", "商业汇报 · 2026.07", 42, 628, 360, 28, 16, {
      color: C.muted,
    });
    setNotes(slide, [
      "/Users/birdy/NyquisteProjects/weixin-blog-publish/docs/weixin-blog-business-architecture.drawio",
      "/Users/birdy/NyquisteProjects/weixin-blog-publish/CONTEXT.md",
      "User-provided Nyquiste AI account, donation, and contribution policy background, 2026-07-27",
    ], "开场只讲业务：这不是一个写作插件，而是一套可运营、可管控的内容秘书处。");
  }

  // Slide 2 — organizational account and compliance context.
  {
    const slide = deck.slides.add();
    slide.background.fill = C.white;
    addSlideHeader(slide, "账号使用权需要一套清晰、可审计的业务依据", 2, "Nyquiste AI 全球全家桶");
    addText(
      slide,
      "account-context-claim",
      "订阅账号注册在 lsforum / lsdforum 名下域名，组织必须能够解释：谁在使用、为何取得、对应款项与贡献如何留痕。",
      42,
      175,
      760,
      150,
      30,
      { bold: true },
    );
    addLine(slide, "account-context-divider", 840, 172, 0, 390, C.rule, 1);
    const accountPoints = [
      ["账号归属组织", "用户获得的是账号使用权，而非账号所有权。"],
      ["资格需要依据", "捐赠与内容贡献构成组织认可用户的业务依据。"],
      ["往来必须留痕", "身份、款项、文章与账号使用资格需要能够相互核验。"],
    ];
    accountPoints.forEach((item, i) => {
      const y = 185 + i * 128;
      addText(slide, `account-point-num-${i + 1}`, `0${i + 1}`, 890, y, 40, 24, 15, {
        color: i === 2 ? C.purple : C.blue,
        bold: true,
      });
      addText(slide, `account-point-title-${i + 1}`, item[0], 940, y - 6, 260, 34, 22, { bold: true });
      addText(slide, `account-point-body-${i + 1}`, item[1], 940, y + 37, 270, 58, 17, { color: C.muted });
    });
    addBox(slide, "account-policy-note", 42, 505, 690, 78, C.paleOrange, "#E7C08C", 12);
    addText(
      slide,
      "account-policy-note-text",
      "合规定位需由法律、财务与组织治理负责人共同确认；本汇报仅描述业务方针。",
      66,
      527,
      640,
      36,
      18,
      { bold: true, color: "#8A4A00" },
    );
    setNotes(slide, [
      "User-provided Nyquiste AI account ownership and compliance background, 2026-07-27",
    ], "强调这是组织治理问题，而不仅是账号采购或费用报销问题。本页不构成法律意见。");
  }

  // Slide 3 — donation and contribution recognition framework.
  {
    const slide = deck.slides.add();
    slide.background.fill = C.white;
    addSlideHeader(slide, "组织以“捐赠 + 内容贡献”形成用户认可依据", 3, "Nyquiste AI 全球全家桶");

    // Relationship lines first.
    addArrow(slide, "recognition-user-donation-arrow", 250, 263, 86, 28, C.orange);
    addArrow(slide, "recognition-user-contribution-arrow", 250, 417, 86, 28, C.blue);
    addArrow(slide, "recognition-donation-org-arrow", 595, 263, 90, 28, C.orange);
    addArrow(slide, "recognition-contribution-org-arrow", 595, 417, 90, 28, C.blue);
    addArrow(slide, "recognition-org-right-arrow", 965, 337, 90, 30, C.purple);

    addBox(slide, "recognition-user", 62, 260, 175, 190, "#F7F7F7", C.rule, 16);
    addText(slide, "recognition-user-title", "用户", 95, 292, 110, 40, 27, { bold: true, align: "center" });
    addText(slide, "recognition-user-body", "认同组织理念\n参与组织生态", 90, 352, 120, 70, 18, {
      color: C.muted,
      align: "center",
    });

    addBox(slide, "recognition-donation", 345, 218, 240, 118, C.paleOrange, C.orange, 14);
    addText(slide, "recognition-donation-title", "捐赠", 375, 244, 100, 35, 25, { bold: true });
    addText(slide, "recognition-donation-body", "用户认同组织理念，并向组织捐赠的款项", 375, 286, 180, 38, 16, {
      color: C.muted,
    });

    addBox(slide, "recognition-contribution", 345, 372, 240, 118, C.paleBlue, C.blue, 14);
    addText(slide, "recognition-contribution-title", "贡献", 375, 398, 100, 35, 25, { bold: true });
    addText(slide, "recognition-contribution-body", "用户提交内容，并经由组织 Blog 发布的文章", 375, 440, 180, 38, 16, {
      color: C.muted,
    });

    addBox(slide, "recognition-organization", 695, 260, 260, 190, C.paleGreen, "#8BCBB7", 16);
    addText(slide, "recognition-organization-title", "组织认可", 750, 292, 150, 40, 27, {
      bold: true,
      color: C.green,
      align: "center",
    });
    addText(slide, "recognition-organization-body", "捐赠者\n贡献者", 765, 352, 120, 70, 22, {
      bold: true,
      align: "center",
    });

    addBox(slide, "recognition-account-right", 1065, 285, 170, 140, C.palePurple, C.purple, 16);
    addText(slide, "recognition-account-right-title", "账号使用权", 1085, 325, 130, 42, 24, {
      bold: true,
      align: "center",
    });
    addText(slide, "recognition-account-right-body", "组织名下订阅账号", 1090, 382, 120, 28, 16, {
      color: C.muted,
      align: "center",
    });

    addBox(slide, "recognition-open-question", 345, 540, 610, 64, C.paleRed, "#E19A9A", 12);
    addText(
      slide,
      "recognition-open-question-text",
      "待明确：捐赠与贡献需同时满足，还是满足其一即可？资格有效期与撤销规则是什么？",
      370,
      557,
      560,
      30,
      18,
      { bold: true, color: C.red, align: "center" },
    );
    setNotes(slide, [
      "User-provided definitions of donation, contribution, recognized users, and account usage rights, 2026-07-27",
    ], "两条路径都构成认可依据，但用户尚未明确 AND/OR 规则，因此在图中保留为管理层待决事项。");
  }

  // Slide 4 — scope boundary.
  {
    const slide = deck.slides.add();
    slide.background.fill = C.white;
    addSlideHeader(slide, "当前项目形成的是“贡献证据链”，不是完整资格系统", 4);
    const columns = [
      ["项目已实现", "微信投稿\n内容抓取\n洗稿产物\n授权发布\n本地留档", C.paleBlue, C.blue],
      ["尚未覆盖", "捐赠款项记录\n捐赠者识别\n账号分配\n到期与撤销", C.paleOrange, C.orange],
      ["后续需对接", "用户身份\n贡献记录\n资格台账\n账号使用权", C.palePurple, C.purple],
    ];
    columns.forEach((col, i) => {
      const x = 42 + i * 412;
      addBox(slide, `scope-column-${i + 1}`, x, 185, 370, 330, col[2], col[3], 16);
      addText(slide, `scope-title-${i + 1}`, col[0], x + 28, 214, 310, 40, 26, { bold: true, color: col[3] });
      addText(slide, `scope-body-${i + 1}`, col[1], x + 28, 290, 310, 185, 21, { bold: true });
    });
    addBox(slide, "scope-conclusion", 42, 558, 1196, 56, C.ink, "none", 12);
    addText(slide, "scope-conclusion-text", "本 repo 可以证明“谁提交了什么、如何处理、是否发布”；完整资格闭环仍需财务与账号管理系统配合。", 68, 575, 1144, 28, 18, {
      color: C.white,
      bold: true,
      align: "center",
    });
    setNotes(slide, [
      "/Users/birdy/NyquisteProjects/weixin-blog-publish/docs/task-repository-layout.md",
      "/Users/birdy/NyquisteProjects/weixin-blog-publish/skills/process-weixin-submissions/SKILL.md",
      "User-provided Nyquiste AI qualification policy background, 2026-07-27",
    ], "主动划清边界：当前项目是贡献证据模块，不应被描述为完整的财务、资格或账号管理系统。");
  }

  // Slide 5 — the exact business architecture developed with the user.
  {
    const slide = deck.slides.add();
    slide.background.fill = C.white;
    addSlideHeader(slide, "秘书处的实际业务架构", 5);
    slide.images.add({
      blob: new Uint8Array(architecturePng),
      contentType: "image/png",
      alt: "用户、秘书处、微信客户端、文件传输助手、Agent、本地任务库与 Blog 的业务架构图",
      fit: "contain",
      position: { left: 60, top: 145, width: 1160, height: 475 },
      geometry: "roundRect",
      borderRadius: 12,
    });
    addText(slide, "architecture-caption", "用户提交指令与 Source；秘书处员工转入文件传输助手；Agent 主动抓取、处理、留档，并在明确授权后发布。", 80, 626, 1120, 28, 16, {
      color: C.muted,
      align: "center",
    });
    setNotes(slide, [
      "/Users/birdy/NyquisteProjects/weixin-blog-publish/docs/weixin-blog-business-architecture.drawio",
      "/Users/birdy/.codex/visualizations/2026/07/27/019fa439-0b2b-7043-a0ce-c8489f950579/weixin-blog-business-overview.html",
      "/Users/birdy/NyquisteProjects/weixin-blog-publish/.tmp/business-briefing/business-architecture.png",
    ], "这是与业务方共同确认的原图，不是为 PPT 重新抽象的版本。");
  }

  // Slide 6 — actual intake format.
  {
    const slide = deck.slides.add();
    slide.background.fill = C.white;
    addSlideHeader(slide, "一条真实投稿如何进入秘书处", 6);
    addArrow(slide, "intake-arrow-1", 360, 348, 58, 28, C.blue);
    addArrow(slide, "intake-arrow-2", 808, 348, 58, 28, C.blue);
    const xs = [42, 430, 878];
    const widths = [318, 378, 360];
    const titles = ["用户提交", "内部员工格式化", "Agent 主动抓取"];
    const fills = [C.paleOrange, C.paleBlue, C.palePurple];
    const strokes = [C.orange, C.blue, C.purple];
    titles.forEach((title, i) => {
      addBox(slide, `intake-card-${i + 1}`, xs[i], 200, widths[i], 330, fills[i], strokes[i], 16);
      addText(slide, `intake-card-title-${i + 1}`, title, xs[i] + 26, 226, widths[i] - 52, 38, 25, { bold: true, color: strokes[i] });
    });
    addText(slide, "intake-user-body", "发文指令\n\nSource：公众号文章卡片\n\n必要时补充作者与处理要求", 72, 300, 258, 190, 20, { bold: true });
    addBox(slide, "intake-sample", 462, 292, 314, 170, C.white, "#B6D7F5", 10);
    addText(slide, "intake-sample-text", "#投稿\n\nauthor.name: birdy-yao\n\n洗稿指令：加强爱国主义精神\n\n[公众号文章卡片]", 482, 308, 274, 140, 17, { bold: true });
    addText(slide, "intake-agent-body", "从文件传输助手识别任务\n\n读取指令与 Source\n\n创建可追踪的任务记录", 912, 302, 292, 170, 20, { bold: true });
    addText(slide, "intake-case-caption", "真实验证文章：独家｜Kimi K3 震荡美股，有望最快 6 个月内港股上市", 42, 574, 1196, 34, 18, {
      color: C.muted,
      align: "center",
    });
    setNotes(slide, [
      "/Users/birdy/NyquisteProjects/weixin-blog-publish/docs/validation/2026-07-24-macos-wechat-full-article-tracer.md",
      "/Users/birdy/NyquisteProjects/weixin-blog-publish/skills/process-weixin-submissions/SKILL.md",
    ], "投稿格式来自真实 tracer：包含 #投稿、author.name、洗稿指令和公众号文章卡片。");
  }

  // Slide 7 — actual Agent operating flow.
  {
    const slide = deck.slides.add();
    slide.background.fill = C.white;
    addSlideHeader(slide, "Agent 在项目里真正执行的五项业务动作", 7);
    addLine(slide, "agent-flow-line", 95, 346, 1085, 0, C.ink, 2);
    const steps = [
      ["01", "识别任务", "解析投稿指令、作者与 Source"],
      ["02", "抓取内容", "取得正文、图片与来源信息"],
      ["03", "洗稿", "按指定要求或版本化规则生成文章"],
      ["04", "构建任务库", "保存原始材料、产物、状态与审计记录"],
      ["05", "发布", "仅在明确授权后提交 Blog"],
    ];
    steps.forEach((step, i) => {
      const x = 65 + i * 242;
      addBox(slide, `agent-step-dot-${i + 1}`, x, 330, 32, 32, i === 4 ? C.purple : C.blue, "none", 16);
      addText(slide, `agent-step-index-${i + 1}`, step[0], x, 336, 32, 16, 11, { color: C.white, bold: true, align: "center" });
      addText(slide, `agent-step-title-${i + 1}`, step[1], x, 392, 190, 40, 23, { bold: true });
      addText(slide, `agent-step-body-${i + 1}`, step[2], x, 445, 190, 95, 17, { color: C.muted });
    });
    addText(slide, "agent-flow-callout", "内容处理与公开发布分离：洗稿完成，不等于必须发布。", 42, 190, 900, 62, 29, { bold: true, color: C.blue });
    setNotes(slide, [
      "/Users/birdy/NyquisteProjects/weixin-blog-publish/skills/process-weixin-submissions/SKILL.md",
      "/Users/birdy/NyquisteProjects/weixin-blog-publish/docs/adr/0009-separate-content-work-from-opt-in-publication.md",
      "/Users/birdy/NyquisteProjects/weixin-blog-publish/docs/task-repository-layout.md",
    ], "五项动作来自当前项目实际 Skill 与任务库设计。");
  }

  // Slide 8 — actual local task repository.
  {
    const slide = deck.slides.add();
    slide.background.fill = C.white;
    addSlideHeader(slide, "本地任务库把每次贡献变成可核验的记录", 8);
    const repoCols = [
      ["runs/", "运行审计", "一次 Agent 执行的状态、报告与本次选择", C.green, C.paleGreen],
      ["tasks/", "投稿与洗稿", "投稿内容、原始抓取、结构化 Source 与改写产物", C.blue, C.paleBlue],
      ["publications/", "发布记录", "独立的发布请求、返回结果与事件轨迹", C.purple, C.palePurple],
    ];
    repoCols.forEach((col, i) => {
      const x = 42 + i * 412;
      addBox(slide, `repo-card-${i + 1}`, x, 205, 370, 300, col[4], col[3], 16);
      addText(slide, `repo-folder-${i + 1}`, col[0], x + 28, 234, 314, 44, 29, { bold: true, color: col[3] });
      addText(slide, `repo-label-${i + 1}`, col[1], x + 28, 302, 314, 38, 24, { bold: true });
      addText(slide, `repo-body-${i + 1}`, col[2], x + 28, 370, 310, 92, 18, { color: C.muted });
    });
    addBox(slide, "repo-linkage", 165, 552, 950, 62, C.ink, "none", 12);
    addText(slide, "repo-linkage-text", "三类记录通过 ID 关联，不互相嵌套；投稿处理与公开发布保持独立。", 195, 570, 890, 28, 19, {
      color: C.white,
      bold: true,
      align: "center",
    });
    setNotes(slide, [
      "/Users/birdy/NyquisteProjects/weixin-blog-publish/docs/task-repository-layout.md",
    ], "这一层是把内容贡献转化为组织证据的关键：谁、何时、提交什么、形成什么结果，都有独立记录。");
  }

  // Slide 9 — real validation evidence.
  {
    const slide = deck.slides.add();
    slide.background.fill = C.white;
    addSlideHeader(slide, "两条真实文章验证了“不发布”与“授权发布”两条路径", 9);
    addBox(slide, "case-a", 42, 175, 570, 420, C.paleBlue, C.blue, 16);
    addText(slide, "case-a-label", "案例 A · 洗稿完成，不发布", 70, 202, 500, 34, 23, { bold: true, color: C.blue });
    addText(slide, "case-a-title", "独家｜Kimi K3 震荡美股，\n有望最快 6 个月内港股上市", 70, 260, 500, 72, 24, { bold: true });
    addText(slide, "case-a-facts", "4,293 字符正文\n13 张静态图片 + 2 个嵌入视频\n洗稿产物已完成\n发布选择：none；发布记录：0", 70, 365, 500, 155, 19, { bold: true });
    addText(slide, "case-a-conclusion", "证明：内容完成后可以受控停止。", 70, 540, 500, 30, 18, { color: C.blue, bold: true });

    addBox(slide, "case-b", 668, 175, 570, 420, C.palePurple, C.purple, 16);
    addText(slide, "case-b-label", "案例 B · 明确授权后发布", 696, 202, 500, 34, 23, { bold: true, color: C.purple });
    addText(slide, "case-b-title", "Chase Total Checking 银行账户\nChecking + Savings $900 奖励", 696, 260, 500, 72, 24, { bold: true });
    addText(slide, "case-b-facts", "2,193 字符正文\n2 个图片位置；GIF 保留静态帧\n发布已确认\n公开地址返回 HTTP 200", 696, 365, 500, 155, 19, { bold: true });
    addText(slide, "case-b-conclusion", "证明：授权后可完成 Blog 发布闭环。", 696, 540, 500, 30, 18, { color: C.purple, bold: true });
    addText(slide, "case-status", "边界说明：两条真实链路已跑通，但仓库状态仍为 core_validated，不能描述为正式上线。", 42, 625, 1196, 28, 17, {
      color: C.red,
      bold: true,
      align: "center",
    });
    setNotes(slide, [
      "/Users/birdy/NyquisteProjects/weixin-blog-publish/docs/validation/2026-07-24-macos-wechat-full-article-tracer.md",
      "/Users/birdy/NyquisteProjects/weixin-blog-publish/docs/validation/2026-07-24-wechat-auto-publication-tracer.md",
    ], "采用真实文章与真实结果，避免用假设性的效率数字。两条 tracer 均明确不等于正式 ready。");
  }

  // Slide 10 — governance and control.
  {
    const slide = deck.slides.add();
    slide.background.fill = C.white;
    addSlideHeader(slide, "自动化越深入，越需要把权限与责任留在人手里", 10);
    addText(
      slide,
      "governance-claim",
      "Agent 可以连续执行，但不能自行扩大任务范围或发布权限。",
      42,
      185,
      590,
      110,
      31,
      { bold: true },
    );
    addText(
      slide,
      "governance-explainer",
      "秘书处的核心不是“无人值守”，而是让人工判断发生在正确的节点。",
      42,
      330,
      520,
      105,
      21,
      { color: C.muted },
    );
    const checks = [
      ["发布默认关闭", "没有明确授权，就不调用 Blog。"],
      ["处理与发布分离", "洗稿完成不代表必须公开。"],
      ["不完整任务不猜测", "缺少关键信息时，回到人工补充。"],
      ["中断可恢复", "历史记录保留，避免盲目重复执行。"],
    ];
    checks.forEach((item, i) => {
      const y = 188 + i * 102;
      addBox(slide, `governance-check-${i + 1}`, 720, y, 32, 32, C.ink, "none", 16);
      addText(slide, `governance-checkmark-${i + 1}`, "✓", 727, y + 4, 18, 20, 16, {
        color: C.white,
        bold: true,
        align: "center",
      });
      addText(slide, `governance-title-${i + 1}`, item[0], 775, y - 3, 390, 34, 22, { bold: true });
      addText(slide, `governance-body-${i + 1}`, item[1], 775, y + 37, 420, 38, 17, { color: C.muted });
    });
    addLine(slide, "governance-divider", 660, 175, 0, 410, C.rule, 1);
    setNotes(slide, [
      "/Users/birdy/NyquisteProjects/weixin-blog-publish/docs/adr/0009-separate-content-work-from-opt-in-publication.md",
      "/Users/birdy/NyquisteProjects/weixin-blog-publish/skills/process-weixin-submissions/SKILL.md",
      "/Users/birdy/NyquisteProjects/weixin-blog-publish/docs/task-repository-layout.md",
    ], "向管理层强调：自动化是执行能力，授权与责任仍由人掌握。");
  }

  // Slide 11 — evidence and remaining gaps.
  {
    const slide = deck.slides.add();
    slide.background.fill = C.white;
    addSlideHeader(slide, "核心链路已经跑通，但项目仍处于受控验证阶段", 11);
    addBox(slide, "progress-verified-area", 42, 185, 550, 390, C.paleGreen, "#8BCBB7", 16);
    addText(slide, "progress-verified-title", "已验证", 72, 214, 200, 42, 28, { bold: true, color: C.green });
    const verified = [
      "真实微信文章完整抓取",
      "真实 Agent 洗稿并生成产物",
      "真实 Blog 自动发布并返回可访问地址",
    ];
    verified.forEach((item, i) => {
      addText(slide, `verified-item-${i + 1}`, `✓  ${item}`, 76, 300 + i * 74, 450, 40, 21, { bold: true });
    });

    addBox(slide, "progress-remaining-area", 640, 185, 598, 390, C.paleOrange, "#E7C08C", 16);
    addText(slide, "progress-remaining-title", "正式上线前仍需完成", 672, 214, 350, 42, 28, {
      bold: true,
      color: "#A25A00",
    });
    const remaining = [
      "多任务真实场景矩阵",
      "正式洗稿规范审批",
      "组合失败与重试验收",
    ];
    remaining.forEach((item, i) => {
      addText(slide, `remaining-item-${i + 1}`, `○  ${item}`, 676, 300 + i * 74, 470, 40, 21, { bold: true });
    });
    addText(slide, "progress-status", "当前判断：核心能力已验证，尚未正式上线", 42, 610, 880, 40, 23, {
      bold: true,
      color: C.blue,
    });
    setNotes(slide, [
      "/Users/birdy/NyquisteProjects/weixin-blog-publish/docs/validation/2026-07-24-macos-wechat-full-article-tracer.md",
      "/Users/birdy/NyquisteProjects/weixin-blog-publish/docs/validation/2026-07-24-wechat-auto-publication-tracer.md",
      "/Users/birdy/NyquisteProjects/weixin-blog-publish/docs/validation/2026-07-24-live-publication-acceptance.md",
      "/Users/birdy/NyquisteProjects/weixin-blog-publish/docs/content-rewrite-policy.md",
    ], "不要把“单条真实链路跑通”讲成“系统已 ready”。仓库的正式状态仍是 core_validated。");
  }

  // Slide 12 — decision and pilot recommendation.
  {
    const slide = deck.slides.add();
    slide.background.fill = C.white;
    addSlideHeader(slide, "建议进入小范围试运行，而不是直接全面上线", 12);
    addLine(slide, "pilot-timeline", 110, 350, 1050, 0, C.ink, 2);
    const milestones = [
      ["01", "限定试运行范围", "固定用户、固定运营人员、有限内容类型"],
      ["02", "补齐管理规则", "洗稿边界、发布权限、异常处理与责任人"],
      ["03", "达成上线门槛", "多任务验收通过，关键风险关闭并完成复盘"],
    ];
    milestones.forEach((m, i) => {
      const x = 105 + i * 380;
      addBox(slide, `pilot-dot-${i + 1}`, x, 332, 36, 36, i === 2 ? C.purple : C.blue, "none", 18);
      addText(slide, `pilot-num-${i + 1}`, m[0], x, 339, 36, 18, 11, {
        color: C.white,
        bold: true,
        align: "center",
      });
      addText(slide, `pilot-title-${i + 1}`, m[1], x, 398, 285, 44, 24, { bold: true });
      addText(slide, `pilot-body-${i + 1}`, m[2], x, 455, 285, 88, 18, { color: C.muted });
    });
    addText(
      slide,
      "pilot-decision",
      "需要管理层确认：资格口径  ·  试运行范围  ·  内容规范负责人  ·  发布授权人",
      42,
      190,
      1130,
      70,
      27,
      { bold: true, color: C.blue },
    );
    addText(slide, "pilot-close", "目标：先形成稳定的运营闭环，再扩大使用范围。", 42, 610, 760, 40, 23, {
      bold: true,
    });
    setNotes(slide, [
      "/Users/birdy/NyquisteProjects/weixin-blog-publish/docs/validation/2026-07-24-wechat-auto-publication-tracer.md",
      "/Users/birdy/NyquisteProjects/weixin-blog-publish/docs/content-rewrite-policy.md",
      "/Users/birdy/NyquisteProjects/weixin-blog-publish/docs/adr/0009-separate-content-work-from-opt-in-publication.md",
      "User-provided Nyquiste AI account qualification policy background, 2026-07-27",
    ], "结束时争取四个管理决策：资格口径、试运行范围、内容规范负责人、发布授权人。");
  }

  for (const [index, slide] of deck.slides.items.entries()) {
    const stem = `slide-${String(index + 1).padStart(2, "0")}`;
    const png = await deck.export({ slide, format: "png", scale: 1 });
    await fs.writeFile(`${PREVIEW_DIR}/${stem}.png`, new Uint8Array(await png.arrayBuffer()));
    const layout = await slide.export({ format: "layout" });
    await fs.writeFile(`${PREVIEW_DIR}/${stem}.layout.json`, await layout.text());
  }

  const montage = await deck.export({ format: "webp", montage: true, scale: 1 });
  await fs.writeFile(
    "/Users/birdy/NyquisteProjects/weixin-blog-publish/.tmp/business-briefing/deck-montage.webp",
    new Uint8Array(await montage.arrayBuffer()),
  );
  const pptx = await PresentationFile.exportPptx(deck);
  await pptx.save(OUTPUT);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
