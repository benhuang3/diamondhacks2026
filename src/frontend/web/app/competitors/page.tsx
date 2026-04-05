import { CompetitorForm } from "@/components/CompetitorForm";
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

export default function CompetitorLanding() {
  return (
    <div className="flex flex-col gap-8">
      <section>
        <Badge variant="outline" className="mb-4">
          Competitor analysis
        </Badge>
        <h1 className="text-3xl font-semibold tracking-tight text-slate-900 sm:text-4xl">
          See what your competitors are charging.
        </h1>
        <p className="mt-3 max-w-2xl text-lg text-slate-600">
          We discover 3–5 comparable stores, extract prices, shipping, tax, and
          promo codes, and tell you exactly where your checkout falls behind.
        </p>
      </section>

      <Card className="max-w-3xl">
        <CardHeader>
          <CardTitle>Start a competitor analysis</CardTitle>
          <CardDescription>
            Give us your store URL and (optionally) a product hint.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <CompetitorForm />
        </CardContent>
      </Card>
    </div>
  );
}
