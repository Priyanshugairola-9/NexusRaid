import { EmptyState } from "../components/ui.jsx";

export default function NotFound() {
  return <EmptyState title="Page not found" action={<a className="btn" href="#/">Go to overview</a>}>This address does not match any page.</EmptyState>;
}
