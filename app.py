import streamlit as st
st.set_page_config(page_title="超级写手", page_icon="🚀", layout="wide")
# 将当前目录加入环境变量
import sys, os
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(current_dir)
import json
from searxng_utils import Search, llm_task, chat
import prompt_template as pt
import concurrent.futures
import subprocess
def install_firefox_with_playwright():
    try:
        # 对于 Windows 系统，你可能需要加上 ".exe" 并确保路径正确
        command = "playwright install --with-deps"
        result = subprocess.run(command, shell=True, check=True)
        command = "playwright install firefox"
        result = subprocess.run(command, shell=True, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        print("安装成功:")
    except subprocess.CalledProcessError as e:
        print("安装失败:", e)

if 'playwright_installed' not in st.session_state:
    install_firefox_with_playwright()
    st.session_state.playwright_installed = True

if "run_status" not in st.session_state:
    st.session_state.run_status = False

with st.sidebar:
    st.title("超级写手配置项：")
    with st.form(key='my_form'):
        text_input = st.text_input(label='请填写文章的主题', help='文章将全部围绕该主题撰写，主题越细，文章也越详细',
                                   value='')
        write_type = st.selectbox('请选择写作模式', ['简易', '详细'], key=2)
        #TODO 因为受到硬件制约，本平台只能用简易模式
        write_type = '简易'
        spider_num = st.slider(label='请选择爬取网页数量（默认5，数量越多时间越长！)', min_value=1, max_value=5, key=3,
                               value=1)
        submit_button = st.form_submit_button(label='执行', disabled=st.session_state.run_status)

st.caption('SuperWriter by WuXiaokun. ')
st.subheader("超级写手🤖", divider='rainbow')

st.info("""

        🆕简介：本应用是利用LLM+搜索引擎+爬虫开发的自动撰写文章的机器人，只需要填写文章主题,程序会自动书写大纲并逐一撰写文章。

        ⚠️注意：整个过程可能需要5分钟-30分钟不到，点击执行后请不要关闭本页面，等待完成后下载文章，刷新或关闭将不会保存。由于硬件平台问题，当前配置项只能使用简易模式，抓取数量为1.
        """)

placeholder_status = st.container()

if submit_button:
    my_bar = placeholder_status.progress(0, text="Operation in progress. Please wait.")
    # *************************** 搜索引擎开始搜索并抓取网页内容 ***************************
    my_bar.progress(10, text="Spider in progress. Please wait...")
    col1, col2 = st.columns(2)
    with col1:
        st.caption("当前进度：")
        placeholder_progress = st.empty()
    with col2:
        st.caption("过程详情预览：")
        placeholder_preview = st.empty()
    with placeholder_progress.container():
        with st.status("抓取网页内容"):
            # 开一个线程运行函数
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(Search(result_num=spider_num).get_search_result, text_input, False if write_type == '简易' else True)
                for future in concurrent.futures.as_completed([future]):
                    search_result = future.result()
        with st.popover("查看搜索详细..."):
            for i in search_result:
                title = i.get('title')
                url = i.get('url')
                st.markdown(f"""
                标题：{title} 
                链接：{url}
                """)
        # *************************** 生成大纲 *************************
        my_bar.progress(30, text="Spider Down! Now generate the outline...")
        with st.status("生成大纲"):
            outlines = llm_task(search_result[:1], text_input, pt.ARTICLE_OUTLINE_GEN)

        # *************************** 融合大纲 *************************
        my_bar.progress(60, text="Integrate article outline...")
        with st.status("融合大纲"):
            outline_summary = chat(f'<topic>{text_input}</topic> <content>{outlines}</content>', pt.ARTICLE_OUTLINE_SUMMARY)
        try:
            outline_summary_json = json.loads(outline_summary.replace('\n', '').replace('```json', '').replace('```', ''))
        except Exception as e:
            print(e, outline_summary)
    with placeholder_preview.container():
        with st.popover("查看大纲"):
            st.json(outline_summary_json)
        st.markdown(f"""
        #### {outline_summary_json['title']} 
    
        > {outline_summary_json['summary']}
        --------------------------
        """)

    # *************************** 书写文章 *************************
    repeat_num = len(outline_summary_json['content_outline'])
    my_bar_article_start = 100 - repeat_num*2
    my_bar.progress(my_bar_article_start, text="Writing article...")
    with st.spinner("书写文章..."):
        n = 1
        article_content = ''
        for outline_block in outline_summary_json['content_outline']:
            my_bar.progress(my_bar_article_start + n*2, text=f"正在撰写  {outline_block['h1']}  {n}/{repeat_num}")
            # 根据抓取的内容资料生成内容
            question = f'<完整大纲>{outline_summary}</完整大纲> 请根据上述信息，书写出以下内容 >>> {outline_block} <<<',
            outline_block_content = llm_task(search_result, question=question,
                                             output_type=pt.ARTICLE_OUTLINE_BLOCK)
            outline_block_content_final = chat(
                f'<完整大纲>{outline_summary}</完整大纲> <相关资料>{outline_block_content}</相关资料> 请根据上述信息，书写大纲中的以下这部分内容：{outline_block}',
                pt.ARTICLE_OUTLINE_BLOCK)
            with st.popover(f'{outline_block["h1"]} {n}/{repeat_num}', use_container_width=True):
                st.markdown(f"""
                {outline_block_content_final}
                """)
            n += 1
            article_content += outline_block_content_final + '   '

    # *************************** 点击下载文章 *************************
    st.download_button(
        label="下载文章",
        data=article_content,
        file_name=f'{text_input}.md',
        mime="text/markdown"
    )