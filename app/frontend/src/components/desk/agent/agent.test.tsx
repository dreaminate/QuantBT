import { describe, it, expect, vi } from "vitest";
import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { render, screen, fireEvent } from "@testing-library/react";
import { ChatBubble } from "./ChatBubble";
import { ChatComposer } from "./ChatComposer";
import { AgentChat, type AgentBlock } from "./AgentChat";

const here = dirname(fileURLToPath(import.meta.url));

describe("G3 Agent 对话组件", () => {
  it("ChatBubble 8 型渲染：user/think/say/todos/tool/patch/gate/workflow", () => {
    const { rerender } = render(<ChatBubble type="user" text="组装策略" />);
    expect(screen.getByText("组装策略")).toBeInTheDocument();

    rerender(<ChatBubble type="think" text="盘算因子集" />);
    expect(screen.getByText("盘算因子集")).toBeInTheDocument();

    rerender(<ChatBubble type="say" text="已选用 fs_core3" />);
    expect(screen.getByText("已选用 fs_core3")).toBeInTheDocument();

    rerender(
      <ChatBubble
        type="todos"
        todos={[
          { text: "建假设", state: "done" },
          { text: "选因子", state: "doing" },
          { text: "跑回测", state: "todo" },
        ]}
      />,
    );
    expect(screen.getByText("Update Todos")).toBeInTheDocument();
    expect(screen.getByText("建假设")).toBeInTheDocument();

    rerender(
      <ChatBubble
        type="tool"
        toolName="backtest.run"
        toolArgs="window=2y"
        toolStatus="done"
        toolSummary="sharpe 1.34"
      />,
    );
    expect(screen.getByText(/backtest\.run/)).toBeInTheDocument();
    expect(screen.getByText(/sharpe 1\.34/)).toBeInTheDocument();

    rerender(
      <ChatBubble
        type="patch"
        patchTitle="加 VaR 节点"
        patchId="pt_4f1a"
        affected="3 处"
        diff={[{ sign: "+", text: "VaR" }]}
      />,
    );
    expect(screen.getByText("加 VaR 节点")).toBeInTheDocument();
    expect(screen.getByText("pt_4f1a")).toBeInTheDocument();

    rerender(
      <ChatBubble
        type="workflow"
        workflowKind="FailureDetected"
        workflowRole="risk_manager"
        workflowDesk="risk"
        workflowAt="2026-07-13T01:02:03Z"
        workflowSummary="failure_stage=provider_call · next_step=retry"
      />,
    );
    const workflow = document.querySelector('[data-block="workflow"]') as HTMLElement;
    expect(workflow.dataset.workflowKind).toBe("FailureDetected");
    expect(screen.getByText("risk_manager · risk")).toBeInTheDocument();
    expect(screen.getByText(/failure_stage=provider_call/)).toBeInTheDocument();
  });

  it("对抗：gate block 默认 expanded=true（种 collapsed 默认必抓）", () => {
    render(
      <ChatBubble type="gate" gateTool="report.generate" gateBlurb="生成报告" />,
    );
    const gate = document.querySelector('[data-block="gate"]') as HTMLElement;
    expect(gate).not.toBeNull();
    expect(gate.dataset.expanded).toBe("true");
    // 普通 gate（side_effect none）可折叠：折叠后 blurb 隐藏。
    expect(screen.getByText("生成报告")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("折叠"));
    expect(screen.queryByText("生成报告")).toBeNull();
  });

  it("对抗 R25：治理弱点 gate（真钱）强制常驻展开、不渲染折叠控件", () => {
    render(
      <ChatBubble
        type="gate"
        gateTool="order.submit"
        sideEffect="realmoney"
        gateBlurb="提交真钱订单"
      />,
    );
    const gate = document.querySelector('[data-block="gate"]') as HTMLElement;
    expect(gate.dataset.governanceWeakness).toBe("true");
    expect(gate.dataset.expanded).toBe("true");
    // 真钱副作用展示 + 弱点提示常驻可见
    expect(screen.getByText("side_effect: realmoney")).toBeInTheDocument();
    expect(screen.getByText(/bypass 也不跳此门/)).toBeInTheDocument();
    // 弱点类绝不渲染折叠按钮——无从折叠藏起
    expect(screen.queryByLabelText("折叠")).toBeNull();
    expect(screen.queryByLabelText("展开")).toBeNull();
  });

  it("对抗 R25：governanceWeakness 显式标记（血统/red 裁决）也强制常驻展开", () => {
    render(
      <ChatBubble
        type="gate"
        gateTool="factor_set.compose"
        sideEffect="none"
        governanceWeakness
        gateBlurb="血统门"
      />,
    );
    const gate = document.querySelector('[data-block="gate"]') as HTMLElement;
    expect(gate.dataset.expanded).toBe("true");
    expect(screen.queryByLabelText("折叠")).toBeNull();
  });

  it("ChatComposer：受控输入 + Enter 发送 + 状态行展示 permissionMode（不可编辑）", () => {
    const onSend = vi.fn();
    const onDraftChange = vi.fn();
    render(
      <ChatComposer
        draft="跑回测"
        onDraftChange={onDraftChange}
        onSend={onSend}
        model="runtime LLM"
        permissionMode="ask"
        branch="strat/weekly-cn"
      />,
    );
    const ta = screen.getByRole("textbox") as HTMLTextAreaElement;
    expect(ta.value).toBe("跑回测");
    fireEvent.keyDown(ta, { key: "Enter" });
    expect(onSend).toHaveBeenCalledTimes(1);
    // 状态行的权限态是展示值，渲染为只读 span，非 input/select（不可编辑/伪造）
    const status = document.querySelector("[data-status-row]") as HTMLElement;
    expect(status).not.toBeNull();
    const perm = status.querySelector('[data-perm-mode="ask"]') as HTMLElement;
    expect(perm).not.toBeNull();
    expect(perm.tagName).toBe("SPAN");
    expect(status.querySelector("input,select,textarea")).toBeNull();
  });

  it("ChatComposer：side_effect/permissionMode 只读展示——状态行无任何表单控件", () => {
    render(
      <ChatComposer
        draft=""
        onDraftChange={() => {}}
        onSend={() => {}}
        model="runtime LLM"
        permissionMode="bypass"
        branch="main"
      />,
    );
    const status = document.querySelector("[data-status-row]") as HTMLElement;
    expect(status.querySelector("input")).toBeNull();
    expect(status.querySelector("select")).toBeNull();
    expect(screen.getByText(/bypass/)).toBeInTheDocument();
  });

  it("AgentChat：blocks map 成 ChatBubble + composer 槽渲染", () => {
    const blocks: AgentBlock[] = [
      { id: "1", type: "user", text: "你好" },
      { id: "2", type: "say", text: "在的" },
      { id: "3", type: "gate", gateTool: "x", gateBlurb: "门" },
    ];
    render(
      <AgentChat
        blocks={blocks}
        contextLabel="上下文 · 18k"
        composer={<div data-testid="composer-slot">composer</div>}
      />,
    );
    expect(screen.getByText("你好")).toBeInTheDocument();
    expect(screen.getByText("在的")).toBeInTheDocument();
    expect(screen.getByText("上下文 · 18k")).toBeInTheDocument();
    expect(screen.getByTestId("composer-slot")).toBeInTheDocument();
  });

  it("对抗#1 token 不漂：agent 组件源码禁裸 hex 色值（须走 --desk-* token）", () => {
    const files = readdirSync(here).filter(
      (f) => /\.tsx?$/.test(f) && !f.includes(".test."),
    );
    const HEX = /#[0-9a-fA-F]{3,8}\b/g;
    const offenders: string[] = [];
    for (const f of files) {
      const hits = readFileSync(join(here, f), "utf8").match(HEX);
      if (hits) offenders.push(`${f}: ${hits.join(",")}`);
    }
    expect(offenders).toEqual([]);
  });
});
