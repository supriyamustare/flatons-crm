import { Link } from "react-router";

export function NotFoundPage() {
  return (
    <div className="py-20 text-center">
      <h1 className="font-display text-2xl text-forest-900">This page doesn’t exist</h1>
      <Link to="/" className="mt-4 inline-block text-sm font-medium text-forest-700 underline">
        Go to the dashboard
      </Link>
    </div>
  );
}
