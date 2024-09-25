# 导入所需的库
import os
import json
import requests
import urllib3
urllib3.disable_warnings()  # 禁用SSL警告
from grab_html_content import get_main_content # 用于获取网页主要内容的函数
import asyncio
import prompt_template  # 提示模板模块
import concurrent.futures  # 并发执行任务
import threading  # 多线程
from transformers import AutoTokenizer
from vllm import LLM, SamplingParams
import streamlit as st

model_name = "hf-models/glm-4-9b-chat"
@st.cache_resource
def get_model(model_name):
    max_model_len, tp_size = 8192, 1
    llm = LLM(
        model=model_name,
        tensor_parallel_size=tp_size,
        max_model_len=max_model_len,
        trust_remote_code=True,
        enforce_eager=True,
        # GLM-4-9B-Chat-1M 如果遇见 OOM 现象，建议开启下述参数
        # enable_chunked_prefill=True,
        max_num_batched_tokens=8192
    )
    return llm

tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
llm = get_model(model_name)
def chat(prompt, system_prompt):
    global tokenizer, llm
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt},
    ]
    stop_token_ids = [151329, 151336, 151338]
    sampling_params = SamplingParams(temperature=0.95, max_tokens=1024, stop_token_ids=stop_token_ids)

    inputs = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    outputs = llm.generate(prompts=inputs, sampling_params=sampling_params)

    response = outputs[0].outputs[0].text
    return response

max_workers = 5
search_result_num = 5
def process_result(content, question, output_type=prompt_template.ARTICLE):
    """
    处理单个搜索结果，生成摘要
    :param content: 搜索结果字典
    :param question: 查询问题
    :param output_type: 输出类型
    :return: 摘要内容
    """
    # print(f'字数统计：{len(content)}')
    if len(content) < 8000:
        html_content = content
    else:
        html_content = content[:8000]
    # 创建对话提示
    chat_result = chat(f'## 参考的上下文资料：<content>{html_content}</content> ## 围绕主题：<topic>{question}</topic> ', output_type)
    # print(f'总结后的字数统计：{len(chat_result)}')
    return chat_result

def llm_task(search_result, question, output_type):
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(process_result, i['html_content'], question, output_type) for i
                   in search_result]
    if output_type == prompt_template.ARTICLE_OUTLINE_GEN:
        # 获取结果
        outlines = '\n'.join([future.result().replace('\n', '').replace('```json', '').replace('```', '') for future in
                              concurrent.futures.as_completed(futures)])
    else:
        # 获取结果
        outlines = '\n'.join([future.result() for future in concurrent.futures.as_completed(futures)])
    if len(outlines) > 8000:
        outlines = outlines[:8000]
    return outlines

class Search:
    def __init__(self, result_num=5):
        """
        初始化搜索引擎类，设置默认结果数量
        :param result_num: 搜索结果数量，默认为8
        """
        self.search_url = "HTTP://searxng.sevnday.top"  # 搜索引擎URL
        self.result_num = result_num  # 结果数量

    def query_search(self, question: str):
        """
        发送请求到搜索引擎，获取JSON响应
        :param question: 查询问题
        :return: JSON数据
        """
        # 优化询问的问题
        # question = chat(question, "根据我的问题重新整理格式并梳理成搜索引擎的查询问题，要求保留原文语意。使用中文。")
        url = self.search_url
        params = {
            "q": question,
            "format": "json",
            "pageno": 1,
            "engines": ','.join(["google", "bing", "yahoo", "duckduckgo", "qwant"]),
            # "categories_exclude": "social",
            # "categories_include": "general",
            # "categories_include_exclude": "include",
            # "categories_exclude_exclude": "exclude",
            # "categories_include_exclude_exclude": "exclude",
        }
        try:
            response = requests.get(url, params=params, verify=False)
            data = response.json()
            return data
        except Exception as e:
            print(e)
            return None

    def get_search_result(self, question: str, spider_mode=False):
        """
        根据问题获取搜索结果
        :param question: 查询问题
        :return: 搜索结果列表
        """
        data = self.query_search(question)
        if data:
            # 过滤并提取合适的搜索结果URL
            search_result = []
            search_engine_urls = []
            for i in data['results'][:self.result_num]:
                if i['url'].split('.')[-1] not in ['xlsx', 'pdf'] and 'bbc' not in i['url'] and i['score'] > 0.1:
                    search_result.append(
                        {'title': i['title'], 'url': i['url'], 'html_content': i['content'] if 'content' in i else ''}
                    )
                    search_engine_urls.append(i['url'])
                    print(i['url'], i['score'], i['title'])
            if spider_mode:
                # 获取网页主要内容
                if len(search_engine_urls) > 0:
                    result = asyncio.run(get_main_content(search_engine_urls))
                    html_content_dict = {i['url']: i['content'].replace('\n', '').replace(' ', '') for i in result}
                    # 构建结果列表
                    for i in search_result:
                        i['html_content'] += html_content_dict[i['url']]
            return search_result
        else:
            return None

    def run(self, question, output_type=prompt_template.ARTICLE, return_type='search'):
        """
        主函数，负责整个程序的流程
        return_type:
            search 返回搜索引擎的结果
            search_spider 返回搜索后并爬取页面的内容的结果
            search_spider_summary 返回搜索-爬取-总结后的结果
        """
        print('搜索中......')
        # 创建Search实例并获取搜索结果
        if return_type == 'search':
            return self.get_search_result(question)
        search_result = self.get_search_result(question, spider_mode=True)
        #TODO 由于硬件限制，暂时只支持单任务。
        search_result = search_result[:1]
        print('抓取完成开始形成摘要......')
        # 使用线程池并发处理结果
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(process_result, i['html_content'], question, output_type) for i in search_result]
        # 收集并合并结果

        lock = threading.Lock()
        combine_contents = ""
        for future in concurrent.futures.as_completed(futures):
            with lock:
                combine_contents += future.result()
        if return_type == 'search_spider':
            return combine_contents
        print('汇总中......')
        if return_type == 'search_spider_summary':
            # 生成最终结果
            result = chat(f'<topic>{question}</topic> <content>{combine_contents}</content>',
                                prompt_template.ARTICLE_FINAL)
            print(result)
            return result

    def auto_writer(self, prompt, outline_summary=''):
        """
        自动生成文章
        :param prompt: 提示词
        :param outline_summary: 大纲
        :return: 生成的文章
        """
        # 首先根据问题获得搜索结果
        search_result = self.get_search_result(prompt, spider_mode=True)
        if len(search_result) == 0:
            return 0
        if outline_summary == '':
            # 根据抓取的每一篇文章生成大纲
            # 使用线程池并发处理结果
            outlines = llm_task(search_result, prompt, prompt_template.ARTICLE_OUTLINE_GEN)
            # 融合多份大纲
            outline_summary = chat(f'<topic>{prompt}</topic> <content>{outlines}</content>', prompt_template.ARTICLE_OUTLINE_SUMMARY)
        try:
            outline_summary_json = json.loads(outline_summary.replace('\n', '').replace('```json', '').replace('```', ''))
        except Exception as e:
            print(e, outline_summary)
            return 0
        repeat_num = len(outline_summary_json['content_outline'])
        # 开始写文章
        article_title = outline_summary_json['title']
        article_summary = outline_summary_json['summary']
        # article_outline = chat(str(outline_summary_json['content_outline']), prompt_template.OUTLINE_MD)
        # 根据大纲一步一步生成文章
        output_path = os.path.join('output', f'{article_title}.md')
        with open(output_path, 'w', encoding='utf-8') as f:
            # f.write(f'# {article_title}\n\n>{article_summary}\n\n[toc]\n\n## 目录：\n{article_outline}\n\n')
            n = 0
            for outline_block in outline_summary_json['content_outline']:
                n += 1
                print(f"{outline_block['h1']} {n}/{repeat_num}")

                # 根据抓取的内容资料生成内容
                question = f'<完整大纲>{outline_summary}</完整大纲> 请根据上述信息，书写出以下内容 >>> {outline_block} <<<',
                outline_block_content = llm_task(search_result, question=question, output_type=prompt_template.ARTICLE_OUTLINE_BLOCK)
                outline_block_content_final = chat(f'<完整大纲>{outline_summary}</完整大纲> <相关资料>{outline_block_content}</相关资料> 请根据上述信息，书写大纲中的以下这部分内容：{outline_block}',
                                       prompt_template.ARTICLE_OUTLINE_BLOCK)
                print(outline_block_content_final)
                # 写入文件
                f.write(outline_block_content_final + '\n\n')