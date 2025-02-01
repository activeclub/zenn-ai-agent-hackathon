import { PrismaClient } from "@prisma/client";

const prisma = new PrismaClient();

async function main() {
  console.log("Start truncating ...");
  for (const { table_name } of await prisma.$queryRaw<
    { table_name: string }[]
  >`SELECT table_name FROM information_schema.tables WHERE table_schema='public';`) {
    await prisma.$executeRawUnsafe(
      `TRUNCATE TABLE "${table_name}" RESTART IDENTITY CASCADE;`
    );
  }
  console.log("Truncating finished.");

  console.log("Start seeding ...");
  await prisma.user.create({
    data: {
      avatarURL:
        "https://storage.googleapis.com/zenn-user-upload/avatar/f083a9af9a.jpeg",
      email: "papa@wondy.io",
      displayName: "パパ",
      settings: {
        create: {},
      },
    },
  });
  console.log("Seeding finished.");
}

main()
  .catch((e) => {
    console.error(e);
    process.exit(1);
  })
  .finally(async () => {
    await prisma.$disconnect();
  });
