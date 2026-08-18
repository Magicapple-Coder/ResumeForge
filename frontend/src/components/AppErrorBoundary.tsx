import { Button, Result } from "antd";
import { Component } from "react";
import type { ErrorInfo, ReactNode } from "react";

interface Props {
  children: ReactNode;
  onReload?: () => void;
}

interface State {
  failed: boolean;
}

export default class AppErrorBoundary extends Component<Props, State> {
  state: State = { failed: false };

  static getDerivedStateFromError(): State {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("ResumeForge UI crashed", error, info);
  }

  private reload = (): void => {
    if (this.props.onReload) {
      this.props.onReload();
      return;
    }
    window.location.reload();
  };

  render(): ReactNode {
    if (!this.state.failed) return this.props.children;

    return (
      <Result
        status="500"
        title="页面暂时无法显示"
        subTitle="界面运行时发生异常，请重新加载后再试。"
        extra={
          <Button type="primary" onClick={this.reload}>
            重新加载
          </Button>
        }
      />
    );
  }
}
