import json
import requests
import threading
from typing import Dict, List, Optional, Tuple
import time

class OpenAIManager:
    def __init__(self, api_key: str, base_url: str = "https://api.openai.com/v1", setting_manager=None):
        """
        初始化OpenAI管理器
        :param api_key: OpenAI API密钥
        :param base_url: API基础URL
        :param setting_manager: 设置管理器实例
        """
        self.api_key = api_key
        self.base_url = base_url
        self.setting_manager = setting_manager
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        })
        
        # 设置连接池参数，增加重试机制
        self.session.mount('https://', requests.adapters.HTTPAdapter(
            max_retries=requests.adapters.Retry(
                total=3,
                backoff_factor=1,
                status_forcelist=[500, 502, 503, 504]
            )
        ))
        
        # 从设置管理器加载经济系统价格配置
        self.economy_prices = self._load_economy_prices()
    
    def _load_economy_prices(self) -> Dict[str, int]:
        """从设置管理器加载经济系统价格配置"""
        if not self.setting_manager:
            # 如果没有设置管理器，使用默认价格
            return {
                "land_per_block": 5000,      # 地价一格5000
                "diamond": 15000,            # 钻石一颗15000
                "log": 20,                   # 原木一块20
                "stone": 10,                 # 石头一块10
                "potato": 30                 # 土豆30一颗
            }
        
        # 从设置管理器读取价格配置
        return {
            "land_per_block": int(self.setting_manager.GetSetting("economy_land_per_block") or "5000"),
            "diamond": int(self.setting_manager.GetSetting("economy_diamond") or "15000"),
            "log": int(self.setting_manager.GetSetting("economy_log") or "20"),
            "stone": int(self.setting_manager.GetSetting("economy_stone") or "10"),
            "potato": int(self.setting_manager.GetSetting("economy_potato") or "30")
        }

    def generate_building_commands(self, center_pos: Tuple[int, int, int], 
                                 size: int, requirements: str, 
                                 player_name: str) -> Tuple[bool, str, List[str], int]:
        """
        生成建筑指令
        :param center_pos: 中心位置 (x, y, z)
        :param size: 建筑范围 (最大64x64)
        :param requirements: 玩家需求描述
        :param player_name: 玩家名称
        :return: (是否成功, 错误信息, 指令列表, 预估价格)
        """
        try:
            # 构建提示词
            prompt = self._build_prompt(center_pos, size, requirements)
            
            # 调用OpenAI API
            response = self._call_openai_api(prompt)
            
            if not response:
                return False, "OpenAI API调用失败", [], 0
            
            # 解析响应
            commands, estimated_cost = self._parse_response(response)
            
            return True, "", commands, estimated_cost
            
        except Exception as e:
            return False, f"生成建筑指令时出错: {str(e)}", [], 0

    def _build_prompt(self, center_pos: Tuple[int, int, int], 
                     size: int, requirements: str) -> str:
        """
        构建发送给AI的提示词
        """
        x, y, z = center_pos
        # 从配置加载经济价格（带默认值兜底）
        prices = self.economy_prices if hasattr(self, 'economy_prices') and self.economy_prices else {}
        land_per_block = int(prices.get("land_per_block", 5000))
        diamond_price = int(prices.get("diamond", 15000))
        log_price = int(prices.get("log", 20))
        stone_price = int(prices.get("stone", 10))
        potato_price = int(prices.get("potato", 30))
        
        prompt = f"""你是一个专业的Minecraft建筑师AI。请根据以下要求生成建筑指令：

建筑位置：中心点({x}, {y}, {z})，范围{size}x{size}格
玩家需求：{requirements}

经济系统价格参考：
- 地价：每格{land_per_block}元
- 钻石：每颗{diamond_price}元  
- 原木：每块{log_price}元
- 石头：每块{stone_price}元
- 土豆：每颗{potato_price}元

请生成以下内容：
1. 建筑指令序列（使用fill或setblock命令）
2. 预估总成本（包括材料成本和地价）

要求：
- 指令必须使用相对坐标，以中心点({x}, {y}, {z})为基准
- 坐标范围：X轴从~-{size//2}到~+{size//2}，Z轴从~-{size//2}到~+{size//2}，Y轴根据需要调整
- 相对坐标格式：负数偏移用~-A，正数偏移用~+A，中心点用~
- 优先使用fill命令提高效率
- 建筑要符合玩家需求
- 合理使用材料，控制成本
- 确保建筑结构稳定美观
- 使用Minecraft Bedrock Edition命令格式
- 不要使用方块状态语法如[facing=east]、[type=top]等
- 不要使用数据值如carpet 0、oak_fence 0、oak_door 0等
- 只使用基本的方块名称，如oak_log、spruce_planks、glass_pane等

**重要：必须包含完整的内饰！**
- 添加家具：床、桌子、椅子、书架、箱子、工作台、熔炉等
- 添加装饰：花盆、画、地毯、楼梯、栅栏等
- 添加照明：蜡烛、火把、灯笼等按照预算灵活调整
- 添加功能区域（面积足够的话）：厨房、卧室、工作区、储物区等
- 使用合适的方块：橡木、云杉木、石头、玻璃等
- 多层建筑要有楼梯或者梯子

请以JSON格式返回：
{{
    "commands": ["fill ~-5 ~ ~-5 ~+5 ~+10 ~+5 stone", "setblock ~ ~+11 ~ diamond_block"],
    "estimated_cost": 125000,
    "description": "建筑描述"
}}

注意：
- 坐标使用相对坐标(~x ~y ~z)，fill命令格式为：fill <from> <to> <block>
- setblock命令格式为：setblock <pos> <block>
- 对于{size}x{size}范围，X和Z坐标应该从~-{size//2}到~+{size//2}
- 例如：10x10范围使用~-5到~+5，8x8范围使用~-4到~+4
- 正数偏移使用~+A格式，负数偏移使用~-A格式，中心点使用~
- 方块参考：https://minecraft.wiki/w/Block
"""
        return prompt

    def _call_openai_api(self, prompt: str) -> Optional[str]:
        """
        调用OpenAI API
        """
        try:
            # 确保URL格式正确
            if self.base_url.endswith('/'):
                url = f"{self.base_url}chat/completions"
            else:
                url = f"{self.base_url}/chat/completions"
            
            # 从设置管理器获取AI配置
            model = self.setting_manager.GetSetting("ai_model") if self.setting_manager else "deepseek-chat"
            
            print(f"[ARC AI Builder] API URL: {url}")
            print(f"[ARC AI Builder] Model: {model}")
            
            data = {
                "model": model,
                "messages": [
                    {
                        "role": "system",
                        "content": "你是一个专业的Minecraft建筑师AI，专门生成建筑指令。请严格按照JSON格式返回结果。"
                    },
                    {
                        "role": "user", 
                        "content": prompt
                    }
                ],
                "stream": False
            }
            
            print(f"[ARC AI Builder] Request data: {json.dumps(data, ensure_ascii=False, indent=2)}")
            
            # 从配置中获取超时设置
            timeout = 60
            max_retries = 3
            if self.setting_manager:
                try:
                    timeout_setting = self.setting_manager.GetSetting("api_timeout")
                    if timeout_setting:
                        timeout = int(timeout_setting)
                except:
                    timeout = 60
                
                try:
                    retries_setting = self.setting_manager.GetSetting("api_max_retries")
                    if retries_setting:
                        max_retries = int(retries_setting)
                except:
                    max_retries = 3
            
            for attempt in range(max_retries):
                try:
                    print(f"[ARC AI Builder] API请求尝试 {attempt + 1}/{max_retries}")
                    response = self.session.post(url, json=data, timeout=timeout)
                    break
                except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError, requests.exceptions.Timeout, requests.exceptions.RequestException) as e:
                    print(f"[ARC AI Builder] API请求超时 (尝试 {attempt + 1}/{max_retries}): {str(e)}")
                    if attempt == max_retries - 1:
                        print(f"[ARC AI Builder] API请求失败，已达到最大重试次数")
                        return None
                    else:
                        wait_time = (attempt + 1) * 5  # 递增等待时间：5秒、10秒、15秒
                        print(f"[ARC AI Builder] 等待 {wait_time} 秒后重试...")
                        time.sleep(wait_time)
            print(f"[ARC AI Builder] Response status: {response.status_code}")
            print(f"[ARC AI Builder] Response headers: {dict(response.headers)}")
            
            if response.status_code != 200:
                print(f"[ARC AI Builder] API Error Response: {response.text}")
                
                # 解析错误信息
                try:
                    error_data = response.json()
                    if "error" in error_data:
                        error_msg = error_data["error"].get("message", "Unknown error")
                        if "Insufficient Balance" in error_msg:
                            print(f"[ARC AI Builder] API余额不足，请充值后重试")
                        elif "Invalid max_tokens" in error_msg:
                            print(f"[ARC AI Builder] max_tokens参数无效: {error_msg}")
                        else:
                            print(f"[ARC AI Builder] API错误: {error_msg}")
                except:
                    print(f"[ARC AI Builder] 无法解析API错误响应")
                
                return None
            
            result = response.json()
            print(f"[ARC AI Builder] API Response: {json.dumps(result, ensure_ascii=False, indent=2)}")
            
            if "choices" not in result or len(result["choices"]) == 0:
                print(f"[ARC AI Builder] No choices in response")
                return None
                
            return result["choices"][0]["message"]["content"]
            
        except Exception as e:
            print(f"[ARC AI Builder] OpenAI API调用失败: {str(e)}")
            import traceback
            print(f"[ARC AI Builder] Traceback: {traceback.format_exc()}")
            return None

    def _parse_response(self, response: str) -> Tuple[List[str], int]:
        """
        解析AI响应，提取指令和成本
        """
        try:
            # 尝试提取JSON部分
            start_idx = response.find('{')
            end_idx = response.rfind('}') + 1
            
            if start_idx == -1 or end_idx == 0:
                raise ValueError("未找到有效的JSON响应")
            
            json_str = response[start_idx:end_idx]
            data = json.loads(json_str)
            
            commands = data.get("commands", [])
            estimated_cost = data.get("estimated_cost", 0)
            
            # 验证指令格式
            validated_commands = []
            for cmd in commands:
                if self._validate_command(cmd):
                    validated_commands.append(cmd)
                else:
                    print(f"[ARC AI Builder] 跳过无效指令: {cmd}")
            
            return validated_commands, estimated_cost
            
        except Exception as e:
            print(f"[ARC AI Builder] 解析AI响应失败: {str(e)}")
            return [], 0

    def _validate_command(self, command: str) -> bool:
        """
        验证指令格式是否正确
        """
        command = command.strip().lower()
        
        # 检查是否是fill或setblock命令
        if command.startswith("fill ") or command.startswith("setblock "):
            return True
        
        return False

    def test_connection(self) -> bool:
        """
        测试API连接
        """
        try:
            # 确保URL格式正确
            if self.base_url.endswith('/'):
                url = f"{self.base_url}models"
            else:
                url = f"{self.base_url}/models"
            
            print(f"[ARC AI Builder] Testing connection to: {url}")
            response = self.session.get(url, timeout=10)
            print(f"[ARC AI Builder] Connection test status: {response.status_code}")
            
            if response.status_code == 200:
                result = response.json()
                print(f"[ARC AI Builder] Available models: {result}")
                return True
            else:
                print(f"[ARC AI Builder] Connection test failed: {response.text}")
                return False
        except Exception as e:
            print(f"[ARC AI Builder] Connection test error: {str(e)}")
            return False
