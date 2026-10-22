import React from "react";

// Last-resort fallback: a render error anywhere would otherwise unmount the whole tree and leave a
// blank page. Shows a plain message (no technical details) and logs the error to the console.
// Sits outside the i18n/theme providers so it still works if one of them is what failed.
export class ErrorBoundary extends React.Component {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error, info) {
    console.error("Unhandled render error", error, info?.componentStack);
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-5 bg-background px-6 text-center text-foreground" role="alert" data-testid="app-error">
        <img src="/brand/logo-icon.png" alt="" className="h-16 w-16 rounded-3xl ring-1 ring-white/15" />
        <div className="space-y-1">
          <h1 className="text-xl font-semibold">Something went wrong</h1>
          <p className="text-sm opacity-75">कुछ गलत हो गया। Please reload the page or go back to the home page.</p>
        </div>
        <div className="flex gap-3">
          <button type="button" onClick={() => window.location.reload()} className="rounded-full bg-hg-violet px-5 py-2 text-sm font-medium text-white">
            Reload
          </button>
          <a href="/" className="rounded-full px-5 py-2 text-sm font-medium ring-1 ring-hg-violet/40">
            Home
          </a>
        </div>
      </div>
    );
  }
}
