import { redirect } from "next/navigation";

/** Legacy URL — Ask lives on the home page now. */
export default function AskRedirectPage() {
  redirect("/");
}
