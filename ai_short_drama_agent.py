import gradio as gr
import requests
import re
import json
import time

# =========================== 配置区域 ===========================
# 【重要】上传GitHub前务必删掉密钥！
API_KEY = "请到硅基流动官网注册获取API Key"
BASE_URL = "https://api.siliconflow.cn/v1/chat/completions"
MODEL = "Qwen/Qwen2.5-32B-Instruct"

HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json; charset=utf-8"
}

MAX_OUTPUT_TOKENS = 16000
MAX_AGENT_ROUNDS = 6
MAX_RETRIES = 2

# =========================== 工具定义 ===========================
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "generate_script",
            "description": "根据用户的故事想法，生成包含8个场景的完整短剧剧本。是全流程的第一步，必须最先执行。",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_idea": {
                        "type": "string",
                        "description": "用户的短剧创意、主题或者详细想法"
                    }
                },
                "required": ["user_idea"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "generate_visual_descriptions",
            "description": "根据已经写好的剧本，提取人物、场景、道具，生成文生图提示词。必须先生成剧本。",
            "parameters": {
                "type": "object",
                "properties": {
                    "script": {
                        "type": "string",
                        "description": "完整的短剧剧本内容"
                    }
                },
                "required": ["script"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "generate_storyboard",
            "description": "根据已经写好的剧本，生成标准化分镜脚本（6-8个单元，每单元3个镜头）。必须先生成剧本。",
            "parameters": {
                "type": "object",
                "properties": {
                    "script": {
                        "type": "string",
                        "description": "完整的短剧剧本内容"
                    }
                },
                "required": ["script"]
            }
        }
    }
]

# =========================== 带重试的大模型调用 ===========================
def call_llm_with_retry(prompt, system="你是一个专业的内容创作者", temp=0.5):
    last_error = ""
    for attempt in range(MAX_RETRIES + 1):
        try:
            payload = {
                "model": MODEL,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt}
                ],
                "temperature": temp,
                "max_tokens": MAX_OUTPUT_TOKENS
            }
            resp = requests.post(BASE_URL, headers=HEADERS, json=payload, timeout=180)
            resp.raise_for_status()
            resp.encoding = 'utf-8'
            result = resp.json()["choices"][0]["message"]["content"]
            result = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', result)
            result = re.sub(r'\f', '', result)
            return result
        except Exception as e:
            last_error = str(e)
            print(f"  第 {attempt+1} 次调用失败：{last_error}")
            time.sleep(1)
            continue
    return f"【生成失败】网络或接口异常，请稍后重试。错误：{last_error}"

# =========================== 三个业务工具函数 ===========================
def generate_script(user_idea):
    prompt = f"""
请根据用户的创意，创作一个完整的短剧剧本：

1. 总长度 1500-2000 字，适合 2 分钟视频。
2. 必须包含 8 个场景，用【场景一】到【场景八】标记。
3. 每个场景包含：地点描述 + 角色动作 + 角色对话。
4. 只输出剧本正文。

用户创意：{user_idea}
"""
    return call_llm_with_retry(prompt, system="你是专业编剧，擅长创作结构紧凑的短剧。")

def generate_visual_descriptions(script):
    prompt = f"""
根据以下剧本，生成文生图提示词：

文生图-人物提示词：
（列出所有角色外貌、着装、气质）

文生图-场景提示词：
（描述环境、光线、氛围）

文生图-道具提示词：
（描述重要道具外观、材质）

剧本：{script}
"""
    return call_llm_with_retry(prompt, system="你是视觉设计师，擅长将文字转化为绘画提示词。")

def generate_storyboard(script):
    scenes = re.findall(r'【场景[一二三四五六七八]】.*?(?=【场景[一二三四五六七八]】|$)', script, re.DOTALL)
    if not scenes:
        paragraphs = script.split('\n\n')
        scenes = paragraphs[:8]
    scene_text = '\n\n'.join(scenes[:8])

    prompt = f"""
【强制指令】严格按要求生成分镜脚本：

1. 生成 6-8 个单元，每个以【时长】15秒开头
2. 每个单元有且只有 3 个镜头：镜头1、镜头2、镜头3
3. 镜头1 时间 (0-5秒)，镜头2 时间 (5-10秒)，镜头3 时间 (10-15秒)
4. 单元之间用空行分隔
5. 禁止添加任何额外文字

【格式模板】：
【时长】15秒
【场景】场景描述
【角色】角色名
【场景道具】道具列表
【手持道具】角色名手持道具
角色固定站位：站位描述
镜头1: (0-5秒) 平视中景，固定镜头，人物动作，人物说："对话"；
镜头2: (5-10秒) 过肩近景，固定镜头，人物动作，人物说："对话"；
镜头3: (10-15秒) 侧方跟拍中景，跟拍镜头，人物动作，人物说："对话"；
光影氛围：光线描述
生成约束：无字幕、无穿模、无变形

【剧本场景】：
{scene_text}
"""
    storyboard = call_llm_with_retry(prompt, system="你是专业分镜师，必须严格按格式输出。")

    def fix_time_format(text):
        lines = text.split('\n')
        new_lines = []
        shot_counter = 0
        for line in lines:
            if '【时长】' in line:
                shot_counter = 0
            if '镜头' in line and ':' in line:
                shot_counter += 1
                if shot_counter == 1:
                    line = re.sub(r'\(\d+-\d+秒\)', '(0-5秒)', line)
                elif shot_counter == 2:
                    line = re.sub(r'\(\d+-\d+秒\)', '(5-10秒)', line)
                elif shot_counter == 3:
                    line = re.sub(r'\(\d+-\d+秒\)', '(10-15秒)', line)
                line = re.sub(r'镜头\d+', f'镜头{shot_counter}', line)
                line = re.sub(r'\((\d+)--(\d+)秒\)', r'(\1-\2秒)', line)
                line = re.sub(r'\(["\'](\d+)-(\d+)秒["\']\)', r'(\1-\2秒)', line)
            new_lines.append(line)
        return '\n'.join(new_lines)

    storyboard = fix_time_format(storyboard)
    return storyboard

# =========================== Agent核心逻辑 ===========================
def call_agent_llm(messages):
    for attempt in range(MAX_RETRIES + 1):
        try:
            payload = {
                "model": MODEL,
                "messages": messages,
                "tools": TOOLS,
                "tool_choice": "auto",
                "temperature": 0.5,
                "max_tokens": 4000
            }
            resp = requests.post(BASE_URL, headers=HEADERS, json=payload, timeout=180)
            resp.raise_for_status()
            resp.encoding = 'utf-8'
            return resp.json()["choices"][0]["message"]
        except Exception as e:
            print(f"  Agent决策第 {attempt+1} 次失败：{str(e)}")
            time.sleep(1)
            continue
    return {"content": "【Agent调用异常】网络不稳定，请重试", "tool_calls": None}

def execute_tool(tool_name, tool_args):
    if tool_name in ["generate_visual_descriptions", "generate_storyboard"]:
        script = tool_args.get("script", "")
        if len(script.strip()) < 50:
            return "提示：剧本内容为空或过短，请先生成剧本。"

    if tool_name == "generate_script":
        return generate_script(**tool_args)
    elif tool_name == "generate_visual_descriptions":
        return generate_visual_descriptions(**tool_args)
    elif tool_name == "generate_storyboard":
        return generate_storyboard(**tool_args)
    return f"未知工具：{tool_name}"

def run_agent(user_idea):
    messages = [
        {
            "role": "system",
            "content": """你是短剧生产助手，按顺序完成：
1. 调用 generate_script 生成剧本
2. 调用 generate_visual_descriptions 生成文生图
3. 调用 generate_storyboard 生成分镜
完成后告知用户。"""
        },
        {"role": "user", "content": f"制作短剧：{user_idea}"}
    ]

    final_script = ""
    final_visual = ""
    final_storyboard = ""
    progress_log = []

    for round_num in range(MAX_AGENT_ROUNDS):
        progress_text = f"🧠 第 {round_num+1} 轮思考..."
        print(f"\n【{progress_text}】")
        yield " | ".join(progress_log) + (f" → {progress_text}" if progress_log else progress_text), final_script, final_visual, final_storyboard

        response = call_agent_llm(messages)
        tool_calls = response.get("tool_calls", None)

        if tool_calls:
            messages.append(response)
            for tool_call in tool_calls:
                tool_name = tool_call["function"]["name"]
                tool_args = json.loads(tool_call["function"]["arguments"])
                tool_id = tool_call["id"]

                step_text = f"⚙️ 执行：{tool_name}"
                print(f"  {step_text}")
                progress_log.append(step_text)
                yield " | ".join(progress_log), final_script, final_visual, final_storyboard

                tool_result = execute_tool(tool_name, tool_args)

                if tool_name == "generate_script":
                    final_script = tool_result
                elif tool_name == "generate_visual_descriptions":
                    final_visual = tool_result
                elif tool_name == "generate_storyboard":
                    final_storyboard = tool_result

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_id,
                    "content": tool_result
                })

                done_text = f"✅ 完成：{tool_name}"
                progress_log.append(done_text)
                yield " | ".join(progress_log), final_script, final_visual, final_storyboard
        else:
            print("✅ Agent任务全部完成")
            progress_log.append("🎉 全部完成")
            yield " | ".join(progress_log), final_script, final_visual, final_storyboard
            return

    progress_log.append("⚠️ 达到最大轮次")
    yield " | ".join(progress_log), final_script, final_visual, final_storyboard

# =========================== Gradio界面 ===========================
with gr.Blocks(title="AI短剧全流程Agent生成器", theme=gr.themes.Soft()) as demo:
    gr.Markdown("""
    # 🎬 AI 短剧全流程 Agent 生成器
    **输入故事想法 → Agent自主调度 → 输出剧本 + 文生图 + 分镜脚本**
    """)

    with gr.Row():
        with gr.Column(scale=1):
            idea = gr.Textbox(label="💡 你的故事想法", lines=6, placeholder="例如：护士在末日自救")
            progress_box = gr.Textbox(label="📋 执行进度", value="等待开始...", interactive=False, lines=2)
            with gr.Row():
                btn = gr.Button("🚀 Agent一键生成", variant="primary")
                clear_btn = gr.Button("🗑️ 清空全部")

        with gr.Column(scale=2):
            script_out = gr.Textbox(label="📖 第一部分：完整剧本", lines=15)
            visual_out = gr.Textbox(label="🎨 第二部分：文生图描述", lines=15)
            storyboard_out = gr.Textbox(label="🎥 第三部分：分镜脚本", lines=30)

    btn.click(
        fn=run_agent,
        inputs=idea,
        outputs=[progress_box, script_out, visual_out, storyboard_out]
    )

    def clear_all():
        return "", "", "", "", "等待开始..."

    clear_btn.click(
        fn=clear_all,
        outputs=[idea, script_out, visual_out, storyboard_out, progress_box]
    )

    gr.Markdown("""
    ---
    ### 📌 使用说明
    - 输入主题或详细想法，Agent自动按顺序生成
    - 进度框实时显示当前执行到哪一步
    - 生成耗时约 1-2 分钟
    - 输出内容可手动选中后 Ctrl+C 复制
    """)

if __name__ == "__main__":
    demo.launch(share=False)