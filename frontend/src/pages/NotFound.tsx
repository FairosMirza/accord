import { ButtonLink, Empty } from "../components/ui";

export default function NotFound() {
  return (
    <Empty title="Page not found" action={<ButtonLink to="/" variant="primary">Go home</ButtonLink>}>
      The link may be old, or you may not have access to it.
    </Empty>
  );
}
