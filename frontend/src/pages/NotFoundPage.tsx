import { Link } from 'react-router'

export function NotFoundPage() {
  return (
    <div className="py-16 text-center">
      <h1 className="text-xl font-semibold">Page not found</h1>
      <Link to="/" className="mt-3 inline-block text-sm font-medium text-teal-700 hover:underline">
        Back to the dashboard
      </Link>
    </div>
  )
}
