# 明日方舟桌面宠物 — 维什戴尔

一个 Windows 11 桌面宠物:透明、无边框、始终置顶的《明日方舟》干员 **维什戴尔**,含两套皮肤(超新星 / 绝对主角)的基建动画与双语言(日文 / 中文)语音。

## 素材来源

- 动画(webm)与语音(wav)来自 [prts.wiki — 维什戴尔](https://prts.wiki/w/%E7%BB%B4%E4%BB%80%E6%88%B4%E5%B0%94),版权归《明日方舟》及其版权方所有
- 本仓库**不包含素材文件**,请自行从 prts.wiki 下载后放入 `resources/Wis'adel/`(文件名规范见下方)

## 项目功能

- 透明无边框置顶窗口,左键拖动、单击交互、滚轮缩放
- 空闲活动循环(移动 / 休息 / 特殊动作)、点击触发交互动画与语音
- 拖到其他窗口上方时角色坐下 / 睡在窗口上,并跟随窗口移动
- 右键菜单:调整大小、设置生日(节日/生日语音播报)、问候、交谈、切换皮肤、切换语音语言(JP / zh-CN)、置顶、退出
- 资源文件名规范:
  - 动画:`维什戴尔-{皮肤}-基建-{动作}-x1.webm`(皮肤: 超新星 / 绝对主角;动作: Interact / Move / Relax / Sit / Sleep / Special)
  - 语音:`{语音名}-{语言}.wav`(语言: JP / zh-CN;语音名: 生日 / 周年庆典 / 新年祝福 / 问候 / 交谈1-3 / 戳一下 / 信赖触摸 / 任命助理 / 闲置)

## 如何启动

```powershell
cd Arknights_Desktop_Pet
python -m pip install -r requirements.txt
python main.py
```

> 依赖:Windows 11 + Python 3.10+(已测试 3.13),素材需按上述规范放入 `resources/Wis'adel/`。
