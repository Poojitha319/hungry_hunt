import { describe, expect, it } from "vitest";
import { captureToken, getToken } from "./token";

describe("token", () => {
  it("captures ?t= from the URL, stores it, and strips it from the address bar", () => {
    window.history.replaceState(null, "", "/job/7?t=abc&x=1");
    captureToken();
    expect(getToken()).toBe("abc");
    expect(window.location.search).toBe("?x=1");
    expect(window.location.pathname).toBe("/job/7");
  });

  it("keeps a previously stored token when the URL has none", () => {
    window.localStorage.setItem("hh_token", "kept");
    window.history.replaceState(null, "", "/");
    captureToken();
    expect(getToken()).toBe("kept");
  });
});
