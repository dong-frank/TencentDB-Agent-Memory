import base64
import os

images = {
    "llm-settings": "LLM 设置界面",
    "create-agent": "创建 Agent",
    "create-task": "创建任务",
    "codebuddy-select-team": "CodeBuddy 选择团队",
    "codebuddy-select-agent": "CodeBuddy 选择 Agent",
    "codebuddy-select-task": "CodeBuddy 选择任务",
    "codegraph-panel-create": "CodeGraph 面板创建",
}

b64 = {}
for name, alt in images.items():
    path = f"{name}.png"
    with open(path, "rb") as f:
        b64[name] = base64.b64encode(f.read()).decode("ascii")
    print(f"  Encoded {name}: {len(b64[name])} chars")

html = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>LGame 知识与记忆工程使用指南</title>
<style>
  :root {
    --bg: #f8f9fa;
    --card-bg: #ffffff;
    --text: #2c3e50;
    --text-secondary: #5a6c7d;
    --accent: #2563eb;
    --accent-hover: #1d4ed8;
    --border: #e2e8f0;
    --shadow: 0 1px 3px rgba(0,0,0,0.08);
    --shadow-hover: 0 4px 12px rgba(0,0,0,0.1);
    --radius: 10px;
    --max-width: 860px;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.75;
    padding: 24px 16px 64px;
  }
  .container {
    max-width: var(--max-width);
    margin: 0 auto;
  }
  h1 {
    font-size: 2rem;
    font-weight: 700;
    text-align: center;
    margin: 32px 0 40px;
    letter-spacing: -0.02em;
  }
  h2 {
    font-size: 1.35rem;
    font-weight: 700;
    margin: 48px 0 16px;
    padding-bottom: 8px;
    border-bottom: 2px solid var(--accent);
    color: var(--accent);
  }
  h3 {
    font-size: 1.1rem;
    font-weight: 600;
    margin: 32px 0 12px;
    color: var(--text);
  }
  p { margin: 0 0 16px; }
  .card {
    background: var(--card-bg);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 24px;
    margin: 0 0 20px;
    box-shadow: var(--shadow);
  }
  .card p:last-child { margin-bottom: 0; }
  .figure {
    margin: 20px 0;
    text-align: center;
  }
  .figure img {
    max-width: 100%;
    border-radius: 6px;
    border: 1px solid var(--border);
    box-shadow: var(--shadow);
    cursor: zoom-in;
    transition: box-shadow 0.2s;
  }
  .figure img:hover { box-shadow: var(--shadow-hover); }
  .figure figcaption {
    margin-top: 8px;
    font-size: 0.9rem;
    color: var(--text-secondary);
  }
  ol, ul { margin: 0 0 16px 24px; }
  li { margin-bottom: 6px; }
  code {
    background: #f1f5f9;
    padding: 2px 6px;
    border-radius: 4px;
    font-size: 0.9em;
    font-family: "SF Mono", "Fira Code", "Cascadia Code", Consolas, monospace;
  }
  strong { color: #b91c1c; }
  .note {
    background: #fef3c7;
    border-left: 4px solid #f59e0b;
    padding: 12px 16px;
    border-radius: 0 6px 6px 0;
    margin: 16px 0;
    font-size: 0.95rem;
  }
  a { color: var(--accent); text-decoration: none; }
  a:hover { text-decoration: underline; }
  .section-nav {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    justify-content: center;
    margin: 0 0 40px;
  }
  .section-nav a {
    display: inline-block;
    padding: 6px 16px;
    background: var(--card-bg);
    border: 1px solid var(--border);
    border-radius: 20px;
    font-size: 0.9rem;
    color: var(--text-secondary);
    transition: all 0.2s;
  }
  .section-nav a:hover {
    background: var(--accent);
    color: #fff;
    border-color: var(--accent);
    text-decoration: none;
  }

  /* Lightbox */
  .lightbox { display: none; position: fixed; z-index: 999; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.85); cursor: zoom-out; justify-content: center; align-items: center; }
  .lightbox.active { display: flex; }
  .lightbox img { max-width: 94vw; max-height: 94vh; border-radius: 6px; }
</style>
</head>
<body>
<div class="container">

<h1>LGame 知识与记忆工程使用指南</h1>

<nav class="section-nav">
  <a href="#login">1. 登录</a>
  <a href="#llm">2. 配置 LLM</a>
  <a href="#start">3. 开始使用</a>
  <a href="#assets">4. 各类资产</a>
</nav>

<!-- ===== 1. 登录 ===== -->
<h2 id="login">1. 登录</h2>
<div class="card">
<p>获取个人 API-KEY（<code>sk-mem...</code> 格式）后，打开链接 <a href="http://dongshenrao-any2.devcloud.woa.com:8125/#/team/members" target="_blank">http://dongshenrao-any2.devcloud.woa.com:8125/#/team/members</a>，输入 API-KEY 完成登录。</p>
</div>

<!-- ===== 2. 配置 LLM ===== -->
<h2 id="llm">2. 配置 LLM</h2>
<div class="card">
<p>点击右上角「设置」，进入上游 LLM 配置界面。</p>
<figure class="figure">
  <img src="data:image/png;base64,IMG_LLM_SETTINGS" alt="LLM 设置界面" onclick="openLightbox(this.src)">
  <figcaption>LLM 设置界面</figcaption>
</figure>
<p>点击「前往获取 Key」获取 CodeBuddy 的 API Key，填入并保存。</p>
</div>

<!-- ===== 3. 开始使用 ===== -->
<h2 id="start">3. 开始使用</h2>

<h3>3.1 创建自己的 Agent</h3>
<div class="card">
<figure class="figure">
  <img src="data:image/png;base64,IMG_CREATE_AGENT" alt="创建 Agent" onclick="openLightbox(this.src)">
  <figcaption>创建 Agent</figcaption>
</figure>
<p>该 Agent 收集到的资产（如 Skill、Chat Memory）会自动保存到其资产库中。默认只有你自己可见；如需共享给团队其他成员，需在面板上手动操作「团队分享」后，其他 Agent 才能访问。</p>
</div>

<h3>3.2 创建自己的任务</h3>
<div class="card">
<figure class="figure">
  <img src="data:image/png;base64,IMG_CREATE_TASK" alt="创建任务" onclick="openLightbox(this.src)">
  <figcaption>创建任务</figcaption>
</figure>
<p>任务在团队中是共享的，一个任务可由多个 Agent、多个用户协作完成。它们仅共享任务描述，<strong>不会共享对话上下文</strong>（对话资产由各自的 Agent 管理，隐私不受影响）。</p>
</div>

<h3>3.3 在 CodeBuddy 中使用</h3>
<div class="card">
<p>配置好初始化 Hook 后：</p>
<ol>
  <li>在 LGame 项目中，<code>unshelve CL 4794028</code> 开始使用。</li>
  <li>新开一个会话，与 CodeBuddy 对话一次，系统会自动配置 <code>~/.codebuddy/models.json</code> 并创建 <code>.codebuddy/project-config-personal.json</code>。</li>
  <li>在 <code>project-config-personal.json</code> 的 <code>tai</code> 字段中配置 API Key。</li>
</ol>
<div class="note">
  <strong>⚠ 注意：</strong>这里填写的是登录用的 <code>sk-mem...</code> 格式 Key，<em>不是</em> CodeBuddy 的 API Key。
</div>
<ol start="4">
  <li>新开一个会话，选择名称以 <code>memory:proxy</code> 开头的模型进行对话。</li>
</ol>
<p>每次新会话启动时，会弹出选择框让你绑定该会话所属的<strong>团队</strong>、<strong>Agent</strong> 和<strong>任务</strong>：</p>
<figure class="figure">
  <img src="data:image/png;base64,IMG_SELECT_TEAM" alt="选择团队" onclick="openLightbox(this.src)">
  <figcaption>选择团队</figcaption>
</figure>
<figure class="figure">
  <img src="data:image/png;base64,IMG_SELECT_AGENT" alt="选择 Agent" onclick="openLightbox(this.src)">
  <figcaption>选择 Agent</figcaption>
</figure>
<figure class="figure">
  <img src="data:image/png;base64,IMG_SELECT_TASK" alt="选择任务" onclick="openLightbox(this.src)">
  <figcaption>选择任务</figcaption>
</figure>
<p>绑定成功后，即可在该会话中使用和积累资产。</p>
</div>

<!-- ===== 4. 各类资产 ===== -->
<h2 id="assets">4. 各类资产</h2>

<h3>4.1 CodeGraph</h3>
<div class="card">
<p><strong>官方用法：</strong>在面板上输入 Git 仓库地址创建。</p>
<figure class="figure">
  <img src="data:image/png;base64,IMG_CODEGRAPH" alt="CodeGraph 面板创建" onclick="openLightbox(this.src)">
  <figcaption>CodeGraph 面板创建</figcaption>
</figure>
<p><strong>扩展用法</strong>（自行开发）：支持对本地目录创建 CodeGraph。在绑定成功的会话中直接输入 Prompt，要求对某个目录创建 CodeGraph 即可（该功能试用中，如有问题请联系）。</p>
<p>创建成功后，需在面板上将 CodeGraph 分配绑定到目标 Agent 上才能使用。</p>
</div>

<h3>4.2 Wiki 知识库</h3>
<div class="card">
<p>在面板上创建 Wiki 知识库后，上传 Markdown 文档即可自动构建。</p>
</div>

<h3>4.3 Skill 技能</h3>
<div class="card">
<p>会话过程中会自动积累 Skill，该过程不会影响 CodeBuddy 本地的 Skill 使用。</p>
</div>

<h3>4.4 Chat Memory</h3>
<div class="card">
<p>会话过程中会自动记录对话原文，并在达到一定轮数后，逐层抽取：</p>
<ul>
  <li><strong>L1</strong> 原子记忆</li>
  <li><strong>L2</strong> 场景记忆</li>
  <li><strong>L3</strong> 核心记忆</li>
</ul>
<p>可在面板上进行分配和管理。默认仅用户自己可见，可选择共享为团队资产。</p>
</div>

</div><!-- .container -->

<!-- Lightbox -->
<div class="lightbox" id="lightbox" onclick="closeLightbox()">
  <img id="lightbox-img" src="" alt="">
</div>

<script>
function openLightbox(src) {
  document.getElementById('lightbox-img').src = src;
  document.getElementById('lightbox').classList.add('active');
}
function closeLightbox() {
  document.getElementById('lightbox').classList.remove('active');
}
document.addEventListener('keydown', function(e) {
  if (e.key === 'Escape') closeLightbox();
});
</script>

</body>
</html>"""

replacements = {
    "IMG_LLM_SETTINGS": b64["llm-settings"],
    "IMG_CREATE_AGENT": b64["create-agent"],
    "IMG_CREATE_TASK": b64["create-task"],
    "IMG_SELECT_TEAM": b64["codebuddy-select-team"],
    "IMG_SELECT_AGENT": b64["codebuddy-select-agent"],
    "IMG_SELECT_TASK": b64["codebuddy-select-task"],
    "IMG_CODEGRAPH": b64["codegraph-panel-create"],
}

for k, v in replacements.items():
    html = html.replace(k, v)

with open("LGame使用指南.html", "w", encoding="utf-8") as f:
    f.write(html)

size_mb = os.path.getsize("LGame使用指南.html") / (1024 * 1024)
print(f"Done: LGame使用指南.html ({size_mb:.1f} MB)")
