import { Link } from "react-router";
import { PageHeader } from "../components/ui";
import { useCurrentUser } from "../hooks/useAuth";
import { ROLE_LABELS } from "../lib/types";

function greeting(): string {
  const hour = new Date().getHours();
  if (hour < 12) return "Good morning";
  if (hour < 17) return "Good afternoon";
  return "Good evening";
}

export function DashboardPage() {
  const user = useCurrentUser();
  const firstName = user.full_name.split(" ")[0];

  return (
    <>
      <PageHeader
        title={`${greeting()}, ${firstName}`}
        description={`Signed in as ${ROLE_LABELS[user.role].toLowerCase()}`}
      />
      <div className="rounded-xl border border-dashed border-line bg-white px-6 py-12 text-center">
        <p className="font-display text-xl text-forest-900">Today’s numbers will appear here</p>
        <p className="mx-auto mt-2 max-w-md text-sm text-muted">
          Once follow-ups and site visits are built, this page will show what’s due today. For now,
          work your enquiries from the Leads page.
        </p>
        <Link
          to="/leads"
          className="mt-6 inline-flex min-h-11 items-center rounded-lg bg-forest-900 px-4 text-sm font-medium text-white hover:bg-forest-800"
        >
          Go to leads
        </Link>
      </div>
    </>
  );
}
