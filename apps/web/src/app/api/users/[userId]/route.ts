import { Prisma, PrismaClient } from "@prisma/client";

const prisma = new PrismaClient();

const defaultSelect = Prisma.validator<Prisma.UserDefaultArgs>()({
  select: {
    id: true,
    avatarURL: true,
    email: true,
    displayName: true,
    settings: {
      select: {
        trait: true,
      },
    },
  },
});

export type User = Prisma.UserGetPayload<typeof defaultSelect>;

export type GetUser = {
  data: User | null;
};

export async function GET(
  request: Request,
  { params }: { params: Promise<{ userId: string }> }
) {
  const user = await prisma.user.findFirst({
    select: defaultSelect.select,
  });

  const res: GetUser = { data: user };

  return Response.json(res);
}

export type PutUser = {
  data: User;
};

export async function PUT(
  req: Request,
  { params }: { params: Promise<{ userId: string }> }
) {
  const { trait } = await req.json();
  const userId = (await params).userId;

  const user = await prisma.user.update({
    where: { id: userId },
    data: {
      settings: {
        update: {
          trait,
        },
      },
    },
    select: defaultSelect.select,
  });

  const res: PutUser = { data: user };

  return Response.json(res);
}
