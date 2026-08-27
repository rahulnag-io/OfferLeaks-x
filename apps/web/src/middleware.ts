export { auth as middleware } from "@/auth";

// Only the routes that actually need a session pay the cost of running
// the auth check -- everything else (marketing pages, the API proxy
// route itself, static assets) is left alone.
export const config = {
  matcher: ["/dashboard/:path*"],
};
